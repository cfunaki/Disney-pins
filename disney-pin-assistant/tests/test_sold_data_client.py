from unittest.mock import AsyncMock, patch
import pytest


@pytest.mark.asyncio
async def test_wrapper_delegates_to_rapidapi_client():
    from src.services import sold_data_client
    expected = {"aggregates": {"average_price": 5.0}, "products": [{"title": "X"}]}
    with patch(
        "src.services.sold_data_client._rapidapi_fetch",
        new=AsyncMock(return_value=expected),
    ) as m:
        result = await sold_data_client.fetch_sold_listings("disney stitch LE 2000", max_results=50)
    assert result == expected
    m.assert_awaited_once_with("disney stitch LE 2000", max_results=50, category_id=None)


@pytest.mark.asyncio
async def test_wrapper_forwards_category_id():
    from src.services import sold_data_client
    with patch(
        "src.services.sold_data_client._rapidapi_fetch",
        new=AsyncMock(return_value={"aggregates": {}, "products": []}),
    ) as m:
        await sold_data_client.fetch_sold_listings("q", max_results=10, category_id="171")
    m.assert_awaited_once_with("q", max_results=10, category_id="171")
