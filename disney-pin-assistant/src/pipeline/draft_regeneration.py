"""Regenerate a pin's listing draft from its current accepted match (or top match)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    Pin, VisionExtraction, CatalogMatch, CatalogEntry,
    MatchStatus, ListingDraft, ExportStatus,
)
from src.pipeline.listing import generate_listing_draft


def _extraction_to_dict(extraction: VisionExtraction) -> dict:
    return {
        "characters": extraction.characters or [],
        "franchise": extraction.franchise,
        "collection_or_series": extraction.collection_or_series,
        "text_on_pin": extraction.text_on_pin,
        "visible_dates": extraction.visible_dates,
        "event_clues": extraction.event_clues,
        "pin_type": extraction.pin_type,
        "edition_size": extraction.edition_size,
        "condition_observations": extraction.condition_observations,
        "suggested_search_terms": extraction.suggested_search_terms or [],
        "confidence_score": extraction.confidence_score,
    }


def _catalog_entry_to_match_dict(entry: CatalogEntry) -> dict:
    return {
        "catalog_entry_id": entry.id,
        "canonical_name": entry.canonical_name,
        "characters": entry.characters,
        "franchise": entry.franchise,
        "event": entry.event,
        "edition_size": entry.edition_size,
        "release_year": entry.release_year,
        "pin_type": entry.pin_type,
    }


async def _resolve_match_entry(db: AsyncSession, pin_id: int, no_catalog_match: bool) -> CatalogEntry | None:
    """Return the catalog entry to use for draft generation, or None if there is none."""
    if no_catalog_match:
        return None

    result = await db.execute(
        select(CatalogMatch)
        .where(CatalogMatch.pin_id == pin_id)
        .where(CatalogMatch.status == MatchStatus.ACCEPTED)
        .limit(1)
    )
    accepted = result.scalar_one_or_none()
    if accepted:
        return await db.get(CatalogEntry, accepted.catalog_entry_id)

    # Fall back to top-ranked suggested match
    result = await db.execute(
        select(CatalogMatch)
        .where(CatalogMatch.pin_id == pin_id)
        .order_by(CatalogMatch.rank.asc())
        .limit(1)
    )
    top = result.scalar_one_or_none()
    if top:
        return await db.get(CatalogEntry, top.catalog_entry_id)

    return None


async def regenerate_draft_for_pin(db: AsyncSession, pin_id: int) -> ListingDraft | None:
    """Rebuild the listing draft for a pin in place. Returns the (new or updated) ListingDraft."""
    pin = await db.get(Pin, pin_id)
    if not pin:
        return None

    extraction_result = await db.execute(
        select(VisionExtraction).where(VisionExtraction.pin_id == pin_id)
    )
    extraction = extraction_result.scalar_one_or_none()
    if not extraction:
        return None

    extraction_dict = _extraction_to_dict(extraction)
    entry = await _resolve_match_entry(db, pin_id, pin.no_catalog_match)
    catalog_match_dict = _catalog_entry_to_match_dict(entry) if entry else None

    draft_data = generate_listing_draft(extraction_dict, catalog_match_dict, pricing=None)

    existing_result = await db.execute(
        select(ListingDraft).where(ListingDraft.pin_id == pin_id)
    )
    draft = existing_result.scalar_one_or_none()

    if draft is None:
        draft = ListingDraft(pin_id=pin_id, export_status=ExportStatus.DRAFT)
        db.add(draft)

    draft.title = draft_data["title"]
    draft.description = draft_data["description"]
    draft.item_specifics = draft_data["item_specifics"]
    draft.suggested_price = draft_data["suggested_price"]
    draft.quick_sale_price = draft_data["quick_sale_price"]
    draft.price_confidence = draft_data["price_confidence"]
    draft.pricing_reasoning = draft_data.get("pricing_reasoning")
    draft.tags_keywords = draft_data["tags_keywords"]

    await db.commit()
    return draft
