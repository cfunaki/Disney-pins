"""eBay Finding API client for retrieving sold listings."""

import asyncio
import xml.etree.ElementTree as ET

import httpx

FINDING_API_URL = "https://svcs.ebay.com/services/search/FindingService/v1"


def parse_finding_response(xml_text: str) -> tuple[list[dict], int]:
    """Parse Finding API XML response into a list of item dicts.

    Returns:
        Tuple of (items, total_pages).
        Each item dict has keys matching Browse API shape for consistency:
        itemId, title, price, image, end_time.
    """
    ns = {"ns": "https://www.ebay.com/marketplace/search/v1/services"}
    root = ET.fromstring(xml_text)

    total_pages_el = root.find(".//ns:paginationOutput/ns:totalPages", ns)
    total_pages = int(total_pages_el.text) if total_pages_el is not None else 0

    items = []
    for item_el in root.findall(".//ns:searchResult/ns:item", ns):
        item_id_el = item_el.find("ns:itemId", ns)
        title_el = item_el.find("ns:title", ns)
        price_el = item_el.find("ns:sellingStatus/ns:currentPrice", ns)
        gallery_el = item_el.find("ns:galleryURL", ns)
        end_time_el = item_el.find("ns:listingInfo/ns:endTime", ns)

        price_dict = {}
        if price_el is not None:
            price_dict = {
                "value": price_el.text,
                "currency": price_el.get("currencyId", "USD"),
            }

        image_dict = {}
        if gallery_el is not None and gallery_el.text:
            image_dict = {"imageUrl": gallery_el.text}

        items.append({
            "itemId": item_id_el.text if item_id_el is not None else "",
            "title": title_el.text if title_el is not None else "",
            "price": price_dict,
            "image": image_dict,
            "end_time": end_time_el.text if end_time_el is not None else None,
        })

    return items, total_pages


async def fetch_sold_listings(
    seller: str,
    app_id: str,
    max_items: int = 200,
    rate_limiter=None,
) -> list[dict]:
    """Fetch completed/sold listings for a seller from the Finding API.

    Args:
        seller: eBay seller username.
        app_id: eBay Application ID (client_id).
        max_items: Maximum listings to fetch.
        rate_limiter: Optional RateLimiter instance.

    Returns:
        List of item dicts (same shape as parse_finding_response output).
    """
    all_items: list[dict] = []
    page = 1

    while len(all_items) < max_items:
        if rate_limiter:
            await rate_limiter.acquire()

        entries_per_page = min(100, max_items - len(all_items))

        params = {
            "OPERATION-NAME": "findCompletedItems",
            "SERVICE-VERSION": "1.13.0",
            "SECURITY-APPNAME": app_id,
            "RESPONSE-DATA-FORMAT": "XML",
            "REST-PAYLOAD": "",
            "categoryId": "13918",
            "itemFilter(0).name": "Seller",
            "itemFilter(0).value": seller,
            "itemFilter(1).name": "SoldItemsOnly",
            "itemFilter(1).value": "true",
            "paginationInput.entriesPerPage": str(entries_per_page),
            "paginationInput.pageNumber": str(page),
            "sortOrder": "EndTimeSoonest",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(FINDING_API_URL, params=params)

        if response.status_code == 429:
            for attempt in range(3):
                backoff = 2 ** (attempt + 1)
                print(f"[finding] 429 rate limited on page {page}, backing off {backoff}s")
                await asyncio.sleep(backoff)
                async with httpx.AsyncClient(timeout=30.0) as retry_client:
                    response = await retry_client.get(FINDING_API_URL, params=params)
                if response.status_code != 429:
                    break
            if response.status_code == 429:
                print(f"[finding] Giving up on page {page} after 429 retries")
                break

        if response.status_code != 200:
            print(f"[finding] Unexpected status {response.status_code} on page {page}")
            break

        items, total_pages = parse_finding_response(response.text)
        if not items:
            break

        all_items.extend(items)
        print(f"[finding] Page {page}/{total_pages}: fetched {len(items)} items (total: {len(all_items)})")

        if page >= total_pages:
            break
        page += 1

    return all_items[:max_items]
