import pytest
from sqlalchemy import select
from src.models import Pin, PinStatus


@pytest.mark.asyncio
async def test_pin_reference_fields_round_trip(db_session):
    pin = Pin(
        batch_id="pnt-eval-2026-04-11",
        status=PinStatus.UNPROCESSED,
        image_paths=["uploads/x.jpg"],
        reference_source="ebay_browse",
        reference_external_id="v1|123|0",
        reference_url="https://www.ebay.com/itm/123",
        reference_raw_title="DSSH Maleficent dragon LE250 new",
        reference_raw_description="boilerplate shipping info",
        reference_parsed_fields={"characters": ["Maleficent"], "edition_size": 250},
        reference_ingested_at="2026-04-11T12:00:00+00:00",
    )
    db_session.add(pin)
    await db_session.commit()

    result = await db_session.execute(select(Pin).where(Pin.batch_id == "pnt-eval-2026-04-11"))
    loaded = result.scalar_one()

    assert loaded.reference_source == "ebay_browse"
    assert loaded.reference_external_id == "v1|123|0"
    assert loaded.reference_url == "https://www.ebay.com/itm/123"
    assert loaded.reference_raw_title == "DSSH Maleficent dragon LE250 new"
    assert loaded.reference_raw_description == "boilerplate shipping info"
    assert loaded.reference_parsed_fields == {"characters": ["Maleficent"], "edition_size": 250}
    assert loaded.reference_ingested_at == "2026-04-11T12:00:00+00:00"


@pytest.mark.asyncio
async def test_pin_reference_fields_default_to_none(db_session):
    pin = Pin(batch_id="normal", status=PinStatus.UNPROCESSED, image_paths=["x.jpg"])
    db_session.add(pin)
    await db_session.commit()

    result = await db_session.execute(select(Pin).where(Pin.batch_id == "normal"))
    loaded = result.scalar_one()

    assert loaded.reference_source is None
    assert loaded.reference_parsed_fields is None
