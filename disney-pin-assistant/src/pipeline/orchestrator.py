import asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from src.config import settings
from src.models import (Pin, PinStatus, VisionExtraction, CatalogMatch, MatchStatus, Comp, ListingType, MatchType, ListingDraft, ExportStatus)
from src.pipeline.vision import extract_pin_metadata
from src.pipeline.matching import find_catalog_matches_hybrid
from src.pipeline.image_matching import compute_clip_embedding
from src.pipeline.comps import search_comps, filter_comps
from src.pipeline.listing import generate_listing_draft, compute_pricing
from src.pipeline.comp_lookup import lookup_comps_for_pin

async def process_single_pin(session_factory: async_sessionmaker, pin_id: int) -> None:
    try:
        await _process_single_pin_inner(session_factory, pin_id)
    except Exception:
        async with session_factory() as db:
            pin = await db.get(Pin, pin_id)
            if pin:
                pin.status = PinStatus.ERROR
                pin.seller_notes = (pin.seller_notes or "") + " [PROCESSING ERROR]"
                await db.commit()

async def _process_single_pin_inner(session_factory: async_sessionmaker, pin_id: int) -> None:
    async with session_factory() as db:
        pin = await db.get(Pin, pin_id)
        if not pin or pin.status != PinStatus.UNPROCESSED:
            return
        extraction_data = await extract_pin_metadata(pin.image_paths)
        extraction = VisionExtraction(
            pin_id=pin.id, characters=extraction_data.get("characters", []),
            franchise=extraction_data.get("franchise"), collection_or_series=extraction_data.get("collection_or_series"),
            text_on_pin=extraction_data.get("text_on_pin"), visible_dates=extraction_data.get("visible_dates"),
            event_clues=extraction_data.get("event_clues"), pin_type=extraction_data.get("pin_type"),
            edition_size=extraction_data.get("edition_size"), condition_observations=extraction_data.get("condition_observations"),
            suggested_search_terms=extraction_data.get("suggested_search_terms", []),
            confidence_score=extraction_data.get("confidence_score", 0.0), raw_api_response=extraction_data,
        )
        db.add(extraction)
        pin.status = PinStatus.EXTRACTED
        await db.commit()

    async with session_factory() as db:
        pin = await db.get(Pin, pin_id)

        # Generate CLIP embedding from user's photo
        query_embedding = None
        try:
            if pin.image_paths:
                query_embedding = compute_clip_embedding(pin.image_paths[0])
        except Exception as exc:
            print(f"[orchestrator] CLIP embedding failed for pin {pin_id}: {exc}")

        matches = await find_catalog_matches_hybrid(
            db, extraction_data,
            query_embedding=query_embedding,
            max_results=3,
        )
        for rank, match in enumerate(matches, 1):
            catalog_match = CatalogMatch(
                pin_id=pin.id, catalog_entry_id=match["catalog_entry_id"],
                match_confidence=match.get("visual_similarity", match["confidence"]),
                match_reasoning=match["reasoning"],
                rank=rank, status=MatchStatus.SUGGESTED,
            )
            db.add(catalog_match)
        if matches:
            pin.status = PinStatus.MATCHED
        await db.commit()

    async with session_factory() as db:
        pin = await db.get(Pin, pin_id)
        search_terms = extraction_data.get("suggested_search_terms", [])
        if matches:
            search_terms = [matches[0]["canonical_name"]] + search_terms

        all_comps = []
        if settings.ebay_client_id and settings.ebay_client_secret:
            sold_comps = await search_comps(search_terms[:1], listing_type="sold")
            active_comps = await search_comps(search_terms[:1], listing_type="active")
            all_comps = filter_comps(sold_comps + active_comps)
            for comp_data in all_comps:
                comp = Comp(
                    pin_id=pin.id, ebay_listing_id=comp_data.get("ebay_listing_id"),
                    title=comp_data["title"], price=comp_data["price"],
                    sale_date=comp_data.get("sale_date"), listing_type=ListingType(comp_data["listing_type"]),
                    condition=comp_data.get("condition"), match_type=MatchType.EXACT if matches else MatchType.NEAR,
                    excluded=comp_data.get("excluded", False), exclusion_reason=comp_data.get("exclusion_reason"),
                    raw_data=comp_data.get("raw_data"),
                )
                db.add(comp)

        pin.status = PinStatus.PRICED
        await db.commit()

    await run_comp_lookup_hook(session_factory, pin_id)

    async with session_factory() as db:
        pin = await db.get(Pin, pin_id)
        best_match = matches[0] if matches else None
        # Load all persisted comps (including weighted RAPIDAPI_SOLD rows from the hook).
        db_comps = (await db.execute(
            select(Comp).where(Comp.pin_id == pin_id)
        )).scalars().all()
        comp_dicts = [
            {
                "price": c.price,
                "listing_type": c.listing_type.value if hasattr(c.listing_type, "value") else c.listing_type,
                "excluded": c.excluded or False,
                "weight": c.weight or 0,
            }
            for c in db_comps
        ]
        pricing = compute_pricing(comp_dicts) if comp_dicts else compute_pricing([
            {"price": c["price"], "listing_type": c["listing_type"], "excluded": c.get("excluded", False), "match_type": c.get("match_type", "near")}
            for c in all_comps
        ])
        draft_data = generate_listing_draft(extraction_data, best_match, pricing)
        draft = ListingDraft(
            pin_id=pin.id, title=draft_data["title"], description=draft_data["description"],
            item_specifics=draft_data["item_specifics"], suggested_price=draft_data["suggested_price"],
            quick_sale_price=draft_data["quick_sale_price"], price_confidence=draft_data["price_confidence"],
            pricing_reasoning=draft_data.get("pricing_reasoning"), tags_keywords=draft_data["tags_keywords"],
            export_status=ExportStatus.DRAFT,
        )
        db.add(draft)
        await db.commit()

async def run_comp_lookup_hook(session_factory: async_sessionmaker, pin_id: int) -> None:
    """Best-effort comp lookup trigger. Failures are logged and swallowed."""
    try:
        await lookup_comps_for_pin(session_factory, pin_id)
    except Exception as exc:
        print(f"[orchestrator] comp lookup failed for pin {pin_id}: {exc}")


async def process_batch(session_factory: async_sessionmaker, batch_id: str) -> None:
    async with session_factory() as db:
        result = await db.execute(select(Pin).where(Pin.batch_id == batch_id, Pin.status == PinStatus.UNPROCESSED))
        pins = result.scalars().all()
        pin_ids = [p.id for p in pins]
    semaphore = asyncio.Semaphore(settings.max_concurrent_processing)
    async def limited_process(pid: int):
        async with semaphore:
            await process_single_pin(session_factory, pid)
    await asyncio.gather(*(limited_process(pid) for pid in pin_ids), return_exceptions=True)
