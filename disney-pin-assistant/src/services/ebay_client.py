import time
import httpx
from src.config import settings

_token_cache: dict = {"access_token": None, "expires_at": 0}

async def get_ebay_token() -> str:
    if _token_cache["access_token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["access_token"]
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.ebay.com/identity/v1/oauth2/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            auth=(settings.ebay_client_id, settings.ebay_client_secret),
            data={"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"},
        )
        response.raise_for_status()
        data = response.json()
        _token_cache["access_token"] = data["access_token"]
        _token_cache["expires_at"] = time.time() + data.get("expires_in", 7200) - 300
        return data["access_token"]

async def browse_api_search(query: str, filters: str | None = None, limit: int = 50) -> list[dict]:
    token = await get_ebay_token()
    params = {"q": query, "limit": str(limit)}
    if filters:
        params["filter"] = filters
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.ebay.com/buy/browse/v1/item_summary/search",
            headers={"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"},
            params=params,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("itemSummaries", [])


async def browse_api_seller_search(seller: str, limit: int = 50) -> list[dict]:
    """Search active listings by seller username."""
    token = await get_ebay_token()
    params = {
        "q": "disney pin",
        "filter": f"sellers:{{{seller}}}",
        "limit": str(limit),
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.ebay.com/buy/browse/v1/item_summary/search",
            headers={"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"},
            params=params,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("itemSummaries", [])


async def browse_api_item_detail(item_id: str) -> dict:
    """Get full item details including localizedAspects."""
    token = await get_ebay_token()
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://api.ebay.com/buy/browse/v1/item/{item_id}",
            headers={"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"},
        )
        response.raise_for_status()
        return response.json()
