import pytest
from unittest.mock import AsyncMock, patch
from src.pipeline.vision import extract_pin_metadata, VISION_PROMPT

def test_vision_prompt_requests_json():
    assert "JSON" in VISION_PROMPT
    assert "characters" in VISION_PROMPT
    assert "franchise" in VISION_PROMPT

@pytest.mark.asyncio
async def test_extract_pin_metadata():
    mock_response = {
        "characters": ["Mickey Mouse"],
        "franchise": "Mickey & Friends",
        "collection_or_series": None,
        "text_on_pin": "Walt Disney World",
        "visible_dates": "2019",
        "event_clues": "Food & Wine Festival",
        "pin_type": "limited edition",
        "edition_size": 3000,
        "condition_observations": "Good condition, no visible scratches",
        "suggested_search_terms": [
            "mickey mouse food wine 2019 pin",
            "disney epcot food wine festival pin le 3000",
        ],
        "confidence_score": 0.85,
    }
    with patch("src.pipeline.vision.call_vision_api", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = mock_response
        result = await extract_pin_metadata(["/fake/path/pin.jpg"])
    assert result["characters"] == ["Mickey Mouse"]
    assert result["franchise"] == "Mickey & Friends"
    assert result["confidence_score"] == 0.85
    assert len(result["suggested_search_terms"]) == 2
    mock_api.assert_called_once()

@pytest.mark.asyncio
async def test_extract_pin_metadata_multiple_images():
    mock_response = {
        "characters": ["Stitch"],
        "franchise": "Lilo & Stitch",
        "collection_or_series": None,
        "text_on_pin": "Disney Parks",
        "visible_dates": None,
        "event_clues": None,
        "pin_type": "enamel",
        "edition_size": None,
        "condition_observations": "Minor wear on edges",
        "suggested_search_terms": ["stitch disney parks pin"],
        "confidence_score": 0.7,
    }
    with patch("src.pipeline.vision.call_vision_api", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = mock_response
        result = await extract_pin_metadata(["/fake/front.jpg", "/fake/back.jpg"])
    assert result["characters"] == ["Stitch"]
    mock_api.assert_called_once()
    call_args = mock_api.call_args
    assert len(call_args[0][0]) == 2
