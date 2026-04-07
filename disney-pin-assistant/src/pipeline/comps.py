import re
from src.services.ebay_client import browse_api_search

LOT_BUNDLE_PATTERNS = [
    re.compile(r"\blot\b", re.IGNORECASE),
    re.compile(r"\blots\b", re.IGNORECASE),
    re.compile(r"\bbundle\b", re.IGNORECASE),
    re.compile(r"\bset of \d+\b", re.IGNORECASE),
    re.compile(r"\b\d+ pins\b", re.IGNORECASE),
    re.compile(r"\b\d+ pin lot\b", re.IGNORECASE),
]

async def ebay_search(search_terms: list[str], listing_type: str) -> list[dict]:
    query = " ".join(search_terms)
    filters = "categoryId:171"
    if listing_type == "sold":
        filters += ",buyingOptions:{FIXED_PRICE}"
    return await browse_api_search(query, filters=filters)

async def search_comps(search_terms: list[str], listing_type: str = "sold") -> list[dict]:
    raw_items = await ebay_search(search_terms, listing_type)
    comps = []
    for item in raw_items:
        price_info = item.get("price", {})
        price = float(price_info.get("value", 0))
        comps.append({
            "ebay_listing_id": item.get("itemId"),
            "title": item.get("title", ""),
            "price": price,
            "sale_date": item.get("itemEndDate"),
            "listing_type": listing_type,
            "condition": item.get("condition"),
            "excluded": False,
            "exclusion_reason": None,
            "raw_data": item,
        })
    return comps

def filter_comps(comps: list[dict]) -> list[dict]:
    for comp in comps:
        title = comp.get("title", "")
        for pattern in LOT_BUNDLE_PATTERNS:
            if pattern.search(title):
                comp["excluded"] = True
                comp["exclusion_reason"] = f"Detected as lot/bundle: matched '{pattern.pattern}'"
                break
    return comps
