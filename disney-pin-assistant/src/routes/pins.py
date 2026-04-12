from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from src.database import get_db
from src.models import Pin, PinStatus, ListingDraft, ExportStatus, CatalogMatch, CatalogEntry, MatchStatus, VisionExtraction
from src.schemas import PinUpdateRequest, MatchSelectRequest, ExtractionPatchRequest
from src.pipeline.draft_regeneration import regenerate_draft_for_pin, extraction_to_dict
from src.pipeline.image_matching import compute_clip_embedding
from src.pipeline.matching import find_catalog_matches_hybrid
from src.pipeline.risk_badges import classify_pin_risk

router = APIRouter(prefix="/api")

@router.get("/batch/{batch_id}/pins")
async def list_batch_pins(batch_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Pin).options(
            selectinload(Pin.extraction),
            selectinload(Pin.listing_draft),
            selectinload(Pin.catalog_matches).selectinload(CatalogMatch.catalog_entry),
            selectinload(Pin.comps),
        ).where(Pin.batch_id == batch_id)
    )
    pins = result.scalars().all()
    return [_serialize_pin(pin) for pin in pins]

async def _load_pin_detail(pin_id: int, db: AsyncSession) -> dict | None:
    """Load a pin with all relations eagerly loaded and return the serialized dict, or None if missing."""
    result = await db.execute(
        select(Pin).options(
            selectinload(Pin.extraction),
            selectinload(Pin.listing_draft),
            selectinload(Pin.catalog_matches).selectinload(CatalogMatch.catalog_entry),
            selectinload(Pin.comps),
        ).where(Pin.id == pin_id)
    )
    pin = result.scalar_one_or_none()
    if not pin:
        return None
    return _serialize_pin(pin)

@router.get("/pins/{pin_id}")
async def get_pin_detail(pin_id: int, db: AsyncSession = Depends(get_db)):
    data = await _load_pin_detail(pin_id, db)
    if data is None:
        raise HTTPException(status_code=404, detail="Pin not found")
    return data

@router.post("/pins/{pin_id}/approve")
async def approve_pin(pin_id: int, db: AsyncSession = Depends(get_db)):
    pin = await db.get(Pin, pin_id)
    if not pin:
        raise HTTPException(status_code=404, detail="Pin not found")
    pin.status = PinStatus.APPROVED
    result = await db.execute(select(ListingDraft).where(ListingDraft.pin_id == pin_id))
    draft = result.scalar_one_or_none()
    if draft:
        draft.export_status = ExportStatus.APPROVED
    await db.commit()
    return await _load_pin_detail(pin_id, db)

@router.post("/pins/{pin_id}/skip")
async def skip_pin(pin_id: int, db: AsyncSession = Depends(get_db)):
    pin = await db.get(Pin, pin_id)
    if not pin:
        raise HTTPException(status_code=404, detail="Pin not found")
    if "[SKIPPED]" not in (pin.seller_notes or ""):
        pin.seller_notes = (pin.seller_notes or "") + " [SKIPPED]"
    await db.commit()
    return await _load_pin_detail(pin_id, db)

@router.patch("/pins/{pin_id}")
async def update_pin(pin_id: int, update: PinUpdateRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Pin).options(
            selectinload(Pin.extraction),
            selectinload(Pin.listing_draft),
            selectinload(Pin.catalog_matches).selectinload(CatalogMatch.catalog_entry),
            selectinload(Pin.comps),
        ).where(Pin.id == pin_id)
    )
    pin = result.scalar_one_or_none()
    if not pin:
        raise HTTPException(status_code=404, detail="Pin not found")
    if pin.listing_draft:
        edits = pin.listing_draft.seller_edits or {}
        if update.title is not None:
            edits["title"] = {"old": pin.listing_draft.title, "new": update.title}
            pin.listing_draft.title = update.title
        if update.description is not None:
            edits["description"] = {"old": pin.listing_draft.description, "new": update.description}
            pin.listing_draft.description = update.description
        if update.suggested_price is not None:
            edits["suggested_price"] = {"old": pin.listing_draft.suggested_price, "new": update.suggested_price}
            pin.listing_draft.suggested_price = update.suggested_price
        if update.tags_keywords is not None:
            pin.listing_draft.tags_keywords = update.tags_keywords
        pin.listing_draft.seller_edits = edits
    if update.seller_notes is not None:
        pin.seller_notes = update.seller_notes
    await db.commit()
    return _serialize_pin(pin)

@router.post("/pins/{pin_id}/match/select")
async def select_match(pin_id: int, body: MatchSelectRequest, db: AsyncSession = Depends(get_db)):
    pin = await db.get(Pin, pin_id)
    if not pin:
        raise HTTPException(status_code=404, detail="Pin not found")

    entry = await db.get(CatalogEntry, body.catalog_entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Catalog entry not found")

    result = await db.execute(select(CatalogMatch).where(CatalogMatch.pin_id == pin_id))
    matches = result.scalars().all()

    chosen = next((m for m in matches if m.catalog_entry_id == body.catalog_entry_id), None)
    if not chosen:
        # Not currently a candidate — insert a new CatalogMatch row for the manual selection
        max_rank = max((m.rank for m in matches), default=0)
        chosen = CatalogMatch(
            pin_id=pin_id,
            catalog_entry_id=body.catalog_entry_id,
            match_confidence=0.0,
            match_reasoning="manually selected by user",
            rank=max_rank + 1,
            status=MatchStatus.ACCEPTED,
        )
        db.add(chosen)
        await db.flush()
        matches.append(chosen)

    for m in matches:
        m.status = MatchStatus.ACCEPTED if m.catalog_entry_id == chosen.catalog_entry_id else MatchStatus.REJECTED

    pin.no_catalog_match = False

    # Regenerate the listing draft from the new accepted match (single atomic transaction)
    await regenerate_draft_for_pin(db, pin_id)
    await db.commit()

    # Return the fresh pin dict (pin already known to exist)
    return await _load_pin_detail(pin_id, db)

@router.post("/pins/{pin_id}/match/none")
async def mark_no_match(pin_id: int, db: AsyncSession = Depends(get_db)):
    pin = await db.get(Pin, pin_id)
    if not pin:
        raise HTTPException(status_code=404, detail="Pin not found")

    result = await db.execute(select(CatalogMatch).where(CatalogMatch.pin_id == pin_id))
    matches = result.scalars().all()
    for m in matches:
        m.status = MatchStatus.REJECTED

    pin.no_catalog_match = True

    await regenerate_draft_for_pin(db, pin_id)
    await db.commit()

    return await _load_pin_detail(pin_id, db)

@router.post("/pins/{pin_id}/extraction")
async def patch_extraction(pin_id: int, body: ExtractionPatchRequest, db: AsyncSession = Depends(get_db)):
    pin = await db.get(Pin, pin_id)
    if not pin:
        raise HTTPException(status_code=404, detail="Pin not found")

    result = await db.execute(select(VisionExtraction).where(VisionExtraction.pin_id == pin_id))
    extraction = result.scalar_one_or_none()
    if not extraction:
        raise HTTPException(status_code=404, detail="Extraction not found for pin")

    if body.characters is not None:
        extraction.characters = body.characters
    if body.franchise is not None:
        extraction.franchise = body.franchise
    if body.pin_type is not None:
        extraction.pin_type = body.pin_type
    if body.edition_size is not None:
        extraction.edition_size = body.edition_size
    if body.visible_dates is not None:
        extraction.visible_dates = body.visible_dates
    if body.event_clues is not None:
        extraction.event_clues = body.event_clues

    await db.commit()
    return await _load_pin_detail(pin_id, db)

@router.post("/pins/{pin_id}/rematch")
async def rematch_pin(pin_id: int, db: AsyncSession = Depends(get_db)):
    pin = await db.get(Pin, pin_id)
    if not pin:
        raise HTTPException(status_code=404, detail="Pin not found")

    extraction_result = await db.execute(
        select(VisionExtraction).where(VisionExtraction.pin_id == pin_id)
    )
    extraction = extraction_result.scalar_one_or_none()
    if not extraction:
        raise HTTPException(status_code=404, detail="Extraction not found for pin")

    extraction_dict = extraction_to_dict(extraction)

    query_embedding = None
    try:
        if pin.image_paths:
            query_embedding = compute_clip_embedding(pin.image_paths[0])
    except Exception as exc:
        import traceback
        print(f"[rematch] CLIP embedding failed for pin {pin_id}: {exc}")
        traceback.print_exc()

    new_matches = await find_catalog_matches_hybrid(
        db, extraction_dict,
        query_embedding=query_embedding,
        max_results=5,
    )

    await db.execute(delete(CatalogMatch).where(CatalogMatch.pin_id == pin_id))
    await db.flush()

    for rank, match in enumerate(new_matches, 1):
        cm = CatalogMatch(
            pin_id=pin_id,
            catalog_entry_id=match["catalog_entry_id"],
            match_confidence=match.get("visual_similarity", match["confidence"]),
            match_reasoning=match.get("reasoning"),
            rank=rank,
            status=MatchStatus.SUGGESTED,
        )
        db.add(cm)

    pin.no_catalog_match = False
    await db.commit()
    return await _load_pin_detail(pin_id, db)

@router.post("/pins/{pin_id}/draft/regenerate")
async def regenerate_draft(pin_id: int, db: AsyncSession = Depends(get_db)):
    pin = await db.get(Pin, pin_id)
    if not pin:
        raise HTTPException(status_code=404, detail="Pin not found")
    await regenerate_draft_for_pin(db, pin_id)
    await db.commit()
    return await _load_pin_detail(pin_id, db)

def _serialize_pin(pin: Pin) -> dict:
    """Serialize a Pin to the wire format with computed risk badge."""
    data = _pin_to_dict(pin)
    data["risk_badge"] = classify_pin_risk(data)
    return data

def _pin_to_dict(pin: Pin) -> dict:
    data = {
        "id": pin.id,
        "batch_id": pin.batch_id,
        "status": pin.status.value,
        "photo_type": pin.photo_type,
        "seller_notes": pin.seller_notes,
        "image_paths": pin.image_paths,
        "no_catalog_match": pin.no_catalog_match,
        "extraction": None,
        "catalog_matches": [],
        "comps": [],
        "listing_draft": None,
    }
    if pin.extraction:
        data["extraction"] = {
            "characters": pin.extraction.characters,
            "franchise": pin.extraction.franchise,
            "pin_type": pin.extraction.pin_type,
            "confidence_score": pin.extraction.confidence_score,
            "suggested_search_terms": pin.extraction.suggested_search_terms,
            "text_on_pin": pin.extraction.text_on_pin,
            "visible_dates": pin.extraction.visible_dates,
            "event_clues": pin.extraction.event_clues,
            "edition_size": pin.extraction.edition_size,
            "condition_observations": pin.extraction.condition_observations,
            "collection_or_series": pin.extraction.collection_or_series,
        }
    for match in pin.catalog_matches:
        entry = match.catalog_entry
        data["catalog_matches"].append({
            "catalog_entry_id": match.catalog_entry_id,
            "match_confidence": match.match_confidence,
            "match_reasoning": match.match_reasoning,
            "rank": match.rank,
            "status": match.status.value,
            "canonical_name": entry.canonical_name if entry else None,
            "image_path": entry.image_path if entry else None,
            "release_year": entry.release_year if entry else None,
            "edition_size": entry.edition_size if entry else None,
            "source": entry.source if entry else None,
        })
    if pin.listing_draft:
        data["listing_draft"] = {
            "title": pin.listing_draft.title,
            "description": pin.listing_draft.description,
            "suggested_price": pin.listing_draft.suggested_price,
            "quick_sale_price": pin.listing_draft.quick_sale_price,
            "price_confidence": pin.listing_draft.price_confidence,
            "pricing_reasoning": pin.listing_draft.pricing_reasoning,
            "tags_keywords": pin.listing_draft.tags_keywords,
            "export_status": pin.listing_draft.export_status.value,
        }
    for comp in pin.comps:
        data["comps"].append({
            "title": comp.title,
            "price": comp.price,
            "listing_type": comp.listing_type.value,
            "excluded": comp.excluded,
            "match_type": comp.match_type.value if comp.match_type else None,
            "weight": comp.weight,
            "sale_date": comp.sale_date,
        })
    if pin.reference_source is not None:
        data["reference_source"] = pin.reference_source
        data["reference_external_id"] = pin.reference_external_id
        data["reference_url"] = pin.reference_url
        data["reference_raw_title"] = pin.reference_raw_title
        data["reference_raw_description"] = pin.reference_raw_description
        data["reference_parsed_fields"] = pin.reference_parsed_fields
        data["reference_ingested_at"] = pin.reference_ingested_at
    return data
