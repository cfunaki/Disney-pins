import csv
import io
import json
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from src.database import get_db
from src.models import CatalogEntry

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
    count = 0
    for item in entries:
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
            source=item.get("source", "import"),
            source_reference_id=item.get("source_reference_id"),
            reference_image_url=item.get("reference_image_url"),
            evidence_strength=item.get("evidence_strength", "medium"),
        )
        db.add(entry)
        count += 1
    await db.commit()
    return {"imported": count}

@router.get("/search")
async def search_catalog(q: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(CatalogEntry).where(CatalogEntry.canonical_name.ilike(f"%{q}%")).limit(20))
    entries = result.scalars().all()
    return [{"id": e.id, "canonical_name": e.canonical_name, "characters": e.characters, "franchise": e.franchise, "event": e.event, "edition_size": e.edition_size, "pin_type": e.pin_type, "evidence_strength": e.evidence_strength} for e in entries]
