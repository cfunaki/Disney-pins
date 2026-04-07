import base64
from pathlib import Path
import anthropic
from src.config import settings

client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

async def send_vision_request(image_paths: list[str], prompt: str) -> str:
    content = []
    for path in image_paths:
        image_data = Path(path).read_bytes()
        base64_image = base64.standard_b64encode(image_data).decode("utf-8")
        suffix = Path(path).suffix.lower()
        media_types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
        media_type = media_types.get(suffix, "image/jpeg")
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": base64_image},
        })
    content.append({"type": "text", "text": prompt})
    response = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{"role": "user", "content": content}],
    )
    return response.content[0].text
