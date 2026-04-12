"""RapidAPI client for eBay sold/completed listing data.

Uses the "eBay Average Selling Price" endpoint on RapidAPI.
Docs: https://rapidapi.com/rpi4gx/api/ebay-average-selling-price
"""

import httpx
from src.config import settings

_RAPIDAPI_URL = "https://ebay-average-selling-price.p.rapidapi.com/findCompletedItems"
_RAPIDAPI_HOST = "ebay-average-selling-price.p.rapidapi.com"


async def fetch_sold_listings(
    keywords: str,
    max_results: int = 240,
    category_id: str | None = None,
) -> dict:
    """Fetch sold eBay listings from RapidAPI.

    Returns:
        {
            "aggregates": {"average_price": ..., "median_price": ..., ...},
            "products": [{"title": ..., "sale_price": ..., "date_sold": ..., "link": ...}, ...],
        }

    Raises:
        ValueError: if rapidapi_key is not configured.
        httpx.HTTPStatusError: on API errors.
    """
    if not settings.rapidapi_key:
        raise ValueError("rapidapi_key is not configured — set RAPIDAPI_KEY in .env")

    body: dict = {
        "keywords": keywords,
        "max_search_results": str(max_results),
    }
    if category_id:
        body["category_id"] = category_id

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            _RAPIDAPI_URL,
            headers={
                "Content-Type": "application/json",
                "X-RapidAPI-Key": settings.rapidapi_key,
                "X-RapidAPI-Host": _RAPIDAPI_HOST,
            },
            json=body,
        )
        response.raise_for_status()
        data = response.json()

    return {
        "aggregates": {
            "average_price": data.get("average_price"),
            "median_price": data.get("median_price"),
            "min_price": data.get("min_price"),
            "max_price": data.get("max_price"),
            "results": data.get("results", 0),
        },
        "products": data.get("products", []),
    }
