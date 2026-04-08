"""Tests for Browse API seller search and item detail functions."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.ebay_client import browse_api_seller_search, browse_api_item_detail


@pytest.mark.asyncio
async def test_browse_api_seller_search_calls_correct_filter():
    """Verify seller search passes the correct filter parameter."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "itemSummaries": [
            {"itemId": "v1|111|0", "title": "Test Pin"}
        ],
        "total": 1,
    }
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("src.services.ebay_client.get_ebay_token", return_value="fake-token"), \
         patch("src.services.ebay_client.httpx.AsyncClient", return_value=mock_client):
        items = await browse_api_seller_search("test_seller", limit=50)

    assert len(items) == 1
    assert items[0]["itemId"] == "v1|111|0"
    # Verify filter includes seller
    call_kwargs = mock_client.get.call_args
    assert "sellers" in call_kwargs.kwargs.get("params", {}).get("filter", "")


@pytest.mark.asyncio
async def test_browse_api_item_detail_returns_full_item():
    """Verify item detail returns full item data including localizedAspects."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "itemId": "v1|222|0",
        "title": "Detailed Pin",
        "localizedAspects": [
            {"name": "Character", "value": "Stitch"}
        ],
    }
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("src.services.ebay_client.get_ebay_token", return_value="fake-token"), \
         patch("src.services.ebay_client.httpx.AsyncClient", return_value=mock_client):
        item = await browse_api_item_detail("v1|222|0")

    assert item["itemId"] == "v1|222|0"
    assert item["localizedAspects"][0]["name"] == "Character"
