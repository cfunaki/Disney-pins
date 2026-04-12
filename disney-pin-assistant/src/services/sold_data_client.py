"""Sold-data source abstraction.

All comp-lookup code should import from here, not directly from
`rapidapi_client`. This keeps a future source swap (Apify, eBay Marketplace
Insights) localized to this file.
"""

from src.services.rapidapi_client import fetch_sold_listings as _rapidapi_fetch


async def fetch_sold_listings(
    query: str,
    max_results: int = 50,
    category_id: str | None = None,
) -> dict:
    """Fetch sold eBay listings.

    Returns:
        {"aggregates": {...}, "products": [...]}
    """
    return await _rapidapi_fetch(query, max_results=max_results, category_id=category_id)
