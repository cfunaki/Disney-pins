import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from src.models import Pin, PinStatus, CatalogMatch
from src.routes.pins import _pin_to_dict


async def _load(db_session, batch_id):
    result = await db_session.execute(
        select(Pin).options(
            selectinload(Pin.extraction),
            selectinload(Pin.listing_draft),
            selectinload(Pin.catalog_matches).selectinload(CatalogMatch.catalog_entry),
            selectinload(Pin.comps),
        ).where(Pin.batch_id == batch_id)
    )
    return result.scalar_one()


@pytest.mark.asyncio
async def test_pin_to_dict_omits_reference_fields_for_normal_uploads(db_session):
    pin = Pin(batch_id="normal", status=PinStatus.UNPROCESSED, image_paths=["x.jpg"])
    db_session.add(pin)
    await db_session.commit()

    loaded = await _load(db_session, "normal")
    data = _pin_to_dict(loaded)

    for key in (
        "reference_source", "reference_external_id", "reference_url",
        "reference_raw_title", "reference_raw_description",
        "reference_parsed_fields", "reference_ingested_at",
    ):
        assert key not in data, f"{key} should be absent for non-reference pins"


@pytest.mark.asyncio
async def test_pin_to_dict_includes_reference_fields_when_present(db_session):
    pin = Pin(
        batch_id="pnt",
        status=PinStatus.UNPROCESSED,
        image_paths=["x.jpg"],
        reference_source="ebay_browse",
        reference_external_id="v1|999|0",
        reference_url="https://www.ebay.com/itm/999",
        reference_raw_title="Stitch LE 500",
        reference_raw_description=None,
        reference_parsed_fields={"characters": ["Stitch"], "edition_size": 500},
        reference_ingested_at="2026-04-11T12:00:00+00:00",
    )
    db_session.add(pin)
    await db_session.commit()

    loaded = await _load(db_session, "pnt")
    data = _pin_to_dict(loaded)

    assert data["reference_source"] == "ebay_browse"
    assert data["reference_external_id"] == "v1|999|0"
    assert data["reference_url"] == "https://www.ebay.com/itm/999"
    assert data["reference_raw_title"] == "Stitch LE 500"
    assert data["reference_raw_description"] is None
    assert data["reference_parsed_fields"] == {"characters": ["Stitch"], "edition_size": 500}
    assert data["reference_ingested_at"] == "2026-04-11T12:00:00+00:00"
