import json
from unittest.mock import AsyncMock, patch, MagicMock
import pytest

from src.services.rapidapi_client import fetch_sold_listings


def _mock_response(data: dict, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    return resp


@pytest.mark.asyncio
async def test_fetch_sold_returns_products_and_aggregates():
    api_response = {
        "average_price": 25.50,
        "median_price": 24.00,
        "min_price": 10.00,
        "max_price": 45.00,
        "results": 3,
        "products": [
            {"title": "Stitch LE 500", "sale_price": "25.00", "date_sold": "Mar 10, 2026", "link": "https://ebay.com/1"},
            {"title": "Stitch LE 500", "sale_price": "24.00", "date_sold": "Mar 08, 2026", "link": "https://ebay.com/2"},
            {"title": "Stitch Pin", "sale_price": "27.50", "date_sold": "Mar 05, 2026", "link": "https://ebay.com/3"},
        ],
    }
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=_mock_response(api_response))

    with patch("src.services.rapidapi_client.httpx.AsyncClient", return_value=mock_client):
        with patch("src.services.rapidapi_client.settings") as mock_settings:
            mock_settings.rapidapi_key = "test-key"
            result = await fetch_sold_listings("Stitch LE 500", max_results=240)

    assert result["aggregates"]["average_price"] == 25.50
    assert result["aggregates"]["median_price"] == 24.00
    assert len(result["products"]) == 3
    assert result["products"][0]["title"] == "Stitch LE 500"
    assert result["products"][0]["sale_price"] == "25.00"
    assert result["products"][0]["date_sold"] == "Mar 10, 2026"
    assert result["products"][0]["link"] == "https://ebay.com/1"


@pytest.mark.asyncio
async def test_fetch_sold_passes_category_id():
    api_response = {"average_price": 0, "median_price": 0, "min_price": 0, "max_price": 0, "results": 0, "products": []}
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=_mock_response(api_response))

    with patch("src.services.rapidapi_client.httpx.AsyncClient", return_value=mock_client):
        with patch("src.services.rapidapi_client.settings") as mock_settings:
            mock_settings.rapidapi_key = "test-key"
            await fetch_sold_listings("pin", max_results=60, category_id="171")

    call_kwargs = mock_client.post.call_args
    body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
    assert body["category_id"] == "171"


@pytest.mark.asyncio
async def test_fetch_sold_raises_on_missing_key():
    with patch("src.services.rapidapi_client.settings") as mock_settings:
        mock_settings.rapidapi_key = ""
        with pytest.raises(ValueError, match="rapidapi_key"):
            await fetch_sold_listings("test")


@pytest.mark.asyncio
async def test_fetch_sold_handles_empty_products():
    api_response = {"average_price": 0, "median_price": 0, "min_price": 0, "max_price": 0, "results": 0, "products": []}
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=_mock_response(api_response))

    with patch("src.services.rapidapi_client.httpx.AsyncClient", return_value=mock_client):
        with patch("src.services.rapidapi_client.settings") as mock_settings:
            mock_settings.rapidapi_key = "test-key"
            result = await fetch_sold_listings("obscure pin")

    assert result["products"] == []
    assert result["aggregates"]["results"] == 0
