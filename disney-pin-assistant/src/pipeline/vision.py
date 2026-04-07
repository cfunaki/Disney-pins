import json
from src.services.anthropic_client import send_vision_request

VISION_PROMPT = """Analyze this Disney pin image(s) and extract metadata. Return ONLY valid JSON with these fields:

{
  "characters": ["list of character names visible"],
  "franchise": "franchise name (e.g., Mickey & Friends, Star Wars, Marvel, Pixar)",
  "collection_or_series": "series or collection name if identifiable, or null",
  "text_on_pin": "any text visible on the pin",
  "visible_dates": "any dates or years visible, or null",
  "event_clues": "any event references (e.g., Food & Wine Festival, Mickey's Not So Scary), or null",
  "pin_type": "one of: enamel, limited edition, mystery, rack, hidden mickey, completer, booster, or other type",
  "edition_size": number or null,
  "condition_observations": "brief condition notes based on what's visible",
  "suggested_search_terms": ["2-4 search phrases to find this pin on eBay"],
  "confidence_score": 0.0 to 1.0
}

If multiple images are provided, the first is typically the front and others may show the backstamp or details. Use all images to improve identification.

Be specific about characters (e.g., "Mickey Mouse" not just "Mickey"). Note any edition markings, event logos, or park-specific indicators. If you're uncertain about any field, set confidence_score lower and explain uncertainty in condition_observations."""

async def call_vision_api(image_paths: list[str]) -> dict:
    raw_response = await send_vision_request(image_paths, VISION_PROMPT)
    text = raw_response.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[:-3]
    return json.loads(text.strip())

async def extract_pin_metadata(image_paths: list[str]) -> dict:
    return await call_vision_api(image_paths)
