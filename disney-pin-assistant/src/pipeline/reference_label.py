"""Reference-label parser: noisy eBay listing title → structured dict.

Used only by scripts/import_ebay_seller.py at ingest time. Calls Claude
Haiku 4.5 with temperature=0. Fields the model is not confident about are
omitted from the output.
"""

import json
from src.services.anthropic_client import client

_MODEL = "claude-haiku-4-5-20251001"

_SYSTEM_PROMPT = """You parse noisy eBay listing titles and descriptions for Disney trading pins into a structured metadata object.

Return JSON with any of these keys, AND ONLY these keys:
- characters: array of Disney character names appearing on the pin
- franchise: string (e.g. "Classic Disney", "Star Wars", "Pixar", "Lilo & Stitch")
- series_or_collection: string (e.g. "Hidden Mickey Series 1")
- release_year: integer
- edition_size: integer (the numeric edition cap, e.g. 2000 for LE 2000)
- is_limited_edition: boolean
- pin_type: string (e.g. "hidden_mickey", "cast_exclusive", "jumbo")
- event: string (e.g. "D23 Expo 2019")
- exclusive_source: string (e.g. "DSSH", "WDI", "Disneyland Paris")
- confidence_notes: free text — always include this field

Omit any key you are not confident about. Do not guess. An omitted key means "not extracted" and is more useful than a wrong guess.

Respond with a single JSON object and no other text. No markdown fences."""


async def parse_listing_label(title: str, description: str | None = None) -> dict | None:
    """Extract structured metadata from a noisy listing title/description.

    Returns a dict of confident fields on success.
    Returns None when the model returns unparseable JSON.
    Raises on transport errors after one retry.
    """
    user_content = f"Title: {title}"
    if description:
        user_content += f"\n\nDescription: {description}"

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            response = await client.messages.create(
                model=_MODEL,
                max_tokens=400,
                temperature=0,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            )
            break
        except Exception as exc:  # noqa: BLE001 — retry any transport/API error once
            last_error = exc
            continue
    else:
        assert last_error is not None
        raise last_error

    raw_text = response.content[0].text.strip()
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        return None
