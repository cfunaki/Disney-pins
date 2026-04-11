from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from src.services import ebay_client


@pytest.mark.asyncio
async def test_seller_search_passes_offset_param():
    ebay_client._token_cache["access_token"] = "fake"
    ebay_client._token_cache["expires_at"] = 9999999999

    captured = {}

    async def _fake_get(self, url, headers=None, params=None):
        captured["url"] = url
        captured["params"] = params
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={"itemSummaries": [{"itemId": "v1|1|0"}]})
        return resp

    with patch("httpx.AsyncClient.get", new=_fake_get):
        items = await ebay_client.browse_api_seller_search(
            seller="pins-n-things", limit=200, offset=400,
        )

    assert items == [{"itemId": "v1|1|0"}]
    assert captured["params"]["offset"] == "400"
    assert captured["params"]["limit"] == "200"
    assert captured["params"]["filter"] == "sellers:{pins-n-things}"


@pytest.mark.asyncio
async def test_seller_search_defaults_offset_to_zero():
    ebay_client._token_cache["access_token"] = "fake"
    ebay_client._token_cache["expires_at"] = 9999999999

    captured = {}

    async def _fake_get(self, url, headers=None, params=None):
        captured["params"] = params
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={"itemSummaries": []})
        return resp

    with patch("httpx.AsyncClient.get", new=_fake_get):
        await ebay_client.browse_api_seller_search(seller="x")

    assert captured["params"]["offset"] == "0"
