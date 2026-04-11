from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from src.database import get_db
from src.models import Pin, PinStatus, ListingDraft, ExportStatus, CatalogMatch, CatalogEntry, MatchStatus
from src.schemas import PinUpdateRequest
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
    dicts = [_pin_to_dict(pin) for pin in pins]
    for d in dicts:
        d["risk_badge"] = classify_pin_risk(d)
    return dicts

@router.get("/pins/{pin_id}")
async def get_pin_detail(pin_id: int, db: AsyncSession = Depends(get_db)):
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
    data = _pin_to_dict(pin)
    data["risk_badge"] = classify_pin_risk(data)
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
    return {"id": pin.id, "status": pin.status.value}

@router.post("/pins/{pin_id}/skip")
async def skip_pin(pin_id: int, db: AsyncSession = Depends(get_db)):
    pin = await db.get(Pin, pin_id)
    if not pin:
        raise HTTPException(status_code=404, detail="Pin not found")
    pin.seller_notes = (pin.seller_notes or "") + " [SKIPPED]"
    await db.commit()
    return {"id": pin.id, "status": pin.status.value, "skipped": True}

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
    return _pin_to_dict(pin)

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
            "tags_keywords": pin.listing_draft.tags_keywords,
            "export_status": pin.listing_draft.export_status.value,
        }
    for comp in pin.comps:
        data["comps"].append({
            "title": comp.title,
            "price": comp.price,
            "listing_type": comp.listing_type.value,
            "excluded": comp.excluded,
        })
    return data
