import csv
import io
import json
import os
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from src.database import get_db
from src.models import CatalogEntry
from src.pipeline.image_matching import compute_clip_embedding


def generate_embedding_for_entry(image_path: str) -> list[float] | None:
    """Generate a CLIP embedding for a catalog entry's image."""
    if not image_path or not os.path.exists(image_path):
        return None
    try:
        return compute_clip_embedding(image_path)
    except Exception as exc:
        print(f"[catalog] Failed to generate embedding for {image_path}: {exc}")
        return None


router = APIRouter(prefix="/api/catalog")

@router.get("/stats")
async def catalog_stats(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(func.count(CatalogEntry.id)))
    total = result.scalar()
    return {"total_entries": total}

@router.post("/import/csv")
async def import_catalog_csv(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    content = await file.read()
    reader = csv.DictReader(io.StringIO(content.decode("utf-8")))
    count = 0
    for row in reader:
        entry = CatalogEntry(
            canonical_name=row.get("name", ""),
            characters=json.loads(row.get("characters", "[]")),
            franchise=row.get("franchise"),
            series_or_collection=row.get("series"),
            event=row.get("event"),
            edition_size=int(row["edition_size"]) if row.get("edition_size") else None,
            release_year=int(row["release_year"]) if row.get("release_year") else None,
            pin_type=row.get("pin_type"),
            exclusive_source=row.get("exclusive_source"),
            source=row.get("source", "manual"),
            source_reference_id=row.get("reference_id"),
            reference_image_url=row.get("image_url"),
            evidence_strength=row.get("evidence_strength", "medium"),
        )
        db.add(entry)
        count += 1
    await db.commit()
    return {"imported": count}

@router.post("/import/json")
async def import_catalog_json(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    content = await file.read()
    entries = json.loads(content.decode("utf-8"))
    if not isinstance(entries, list):
        raise HTTPException(status_code=400, detail="Expected a JSON array")

    # Build a set of existing (source, source_reference_id) pairs to detect duplicates
    existing_result = await db.execute(
        select(CatalogEntry.source, CatalogEntry.source_reference_id).where(
            CatalogEntry.source_reference_id.isnot(None)
        )
    )
    existing_pairs = {(row[0], row[1]) for row in existing_result.all()}

    count = 0
    skipped = 0
    for item in entries:
        source = item.get("source", "import")
        ref_id = item.get("source_reference_id")
        if ref_id is not None and (source, ref_id) in existing_pairs:
            skipped += 1
            continue
        entry = CatalogEntry(
            canonical_name=item.get("canonical_name", item.get("name", "")),
            alternate_names=item.get("alternate_names", []),
            characters=item.get("characters", []),
            franchise=item.get("franchise"),
            series_or_collection=item.get("series_or_collection"),
            event=item.get("event"),
            edition_size=item.get("edition_size"),
            release_year=item.get("release_year"),
            pin_type=item.get("pin_type"),
            exclusive_source=item.get("exclusive_source"),
            source=source,
            source_reference_id=ref_id,
            reference_image_url=item.get("reference_image_url"),
            image_path=item.get("image_path"),
            evidence_strength=item.get("evidence_strength", "medium"),
        )
        db.add(entry)
        # Generate CLIP embedding if image is available
        image_path = item.get("image_path")
        if image_path:
            embedding = generate_embedding_for_entry(image_path)
            if embedding:
                entry.clip_embedding = json.dumps(embedding)
        count += 1
        if ref_id is not None:
            existing_pairs.add((source, ref_id))
    await db.commit()
    return {"imported": count, "skipped": skipped}

@router.get("/search")
async def search_catalog(q: str, offset: int = 0, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(CatalogEntry)
        .where(CatalogEntry.canonical_name.ilike(f"%{q}%"))
        .order_by(CatalogEntry.canonical_name.asc(), CatalogEntry.id.asc())
        .offset(offset)
        .limit(20)
    )
    entries = result.scalars().all()
    return [
        {
            "id": e.id,
            "canonical_name": e.canonical_name,
            "characters": e.characters,
            "franchise": e.franchise,
            "event": e.event,
            "edition_size": e.edition_size,
            "pin_type": e.pin_type,
            "evidence_strength": e.evidence_strength,
            "image_path": e.image_path,
            "release_year": e.release_year,
            "source": e.source,
        }
        for e in entries
    ]
