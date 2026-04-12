import pytest
from unittest.mock import AsyncMock, patch
from src.pipeline.comps import search_comps, filter_comps

@pytest.mark.asyncio
async def test_search_comps():
    mock_items = [
        {"itemId": "111", "title": "Mickey Mouse Food Wine 2019 Pin LE 3000", "price": {"value": "24.99", "currency": "USD"}, "condition": "New", "itemEndDate": "2026-03-15"},
        {"itemId": "222", "title": "Mickey Mouse Pin Lot of 10", "price": {"value": "45.00", "currency": "USD"}, "condition": "Used", "itemEndDate": "2026-03-10"},
    ]
    with patch("src.pipeline.comps.ebay_search", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = mock_items
        results = await search_comps(search_terms=["mickey mouse food wine 2019 pin le 3000"], listing_type="sold")
    assert len(results) == 2
    assert results[0]["ebay_listing_id"] == "111"
    assert results[0]["price"] == 24.99

def test_filter_comps_excludes_lots():
    comps = [
        {"title": "Mickey Mouse Food Wine 2019 Pin LE 3000", "price": 24.99, "excluded": False, "exclusion_reason": None},
        {"title": "Mickey Mouse Pin Lot of 10 Disney Pins", "price": 45.00, "excluded": False, "exclusion_reason": None},
        {"title": "Disney Pin Bundle 20 Random Pins", "price": 30.00, "excluded": False, "exclusion_reason": None},
    ]
    filtered = filter_comps(comps)
    included = [c for c in filtered if not c["excluded"]]
    excluded = [c for c in filtered if c["excluded"]]
    assert len(included) == 1
    assert included[0]["title"] == "Mickey Mouse Food Wine 2019 Pin LE 3000"
    assert len(excluded) == 2

def test_filter_comps_keeps_singles():
    comps = [
        {"title": "Stitch Surfing Disney Pin", "price": 12.00, "excluded": False, "exclusion_reason": None},
        {"title": "Mickey Mouse Classic Pin", "price": 8.00, "excluded": False, "exclusion_reason": None},
    ]
    filtered = filter_comps(comps)
    assert all(not c["excluded"] for c in filtered)


def test_match_type_has_rapidapi_sold():
    from src.models import MatchType
    assert MatchType.RAPIDAPI_SOLD.value == "rapidapi_sold"


from sqlalchemy import select as _select_weight


@pytest.mark.asyncio
async def test_comp_weight_column_round_trip(db_session):
    from src.models import Comp, MatchType, ListingType, Pin, PinStatus
    pin = Pin(batch_id="b1", image_paths=[], status=PinStatus.UNPROCESSED)
    db_session.add(pin)
    await db_session.flush()
    comp = Comp(
        pin_id=pin.id,
        title="Test pin",
        price=10.0,
        listing_type=ListingType.SOLD,
        match_type=MatchType.RAPIDAPI_SOLD,
        weight=0.42,
    )
    db_session.add(comp)
    await db_session.commit()
    loaded = (await db_session.execute(_select_weight(Comp).where(Comp.id == comp.id))).scalar_one()
    assert loaded.weight == 0.42
