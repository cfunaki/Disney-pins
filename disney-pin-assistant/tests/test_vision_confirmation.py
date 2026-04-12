import json
import pytest
from unittest.mock import patch, AsyncMock
from src.pipeline.matching import confirm_match_with_vision


@pytest.mark.asyncio
async def test_vision_confirms_best_match():
    candidates = [
        {"catalog_entry_id": 1, "canonical_name": "Mickey 50th Anniversary", "image_path": "catalog_images/100.jpg", "visual_similarity": 0.85},
        {"catalog_entry_id": 2, "canonical_name": "Mickey Holiday", "image_path": "catalog_images/101.jpg", "visual_similarity": 0.80},
    ]
    mock_response = json.dumps({"best_match_catalog_entry_id": 1, "confidence": "high", "reasoning": "Same pose and background design"})
    with patch("src.pipeline.matching.send_vision_request", new_callable=AsyncMock, return_value=mock_response):
        result = await confirm_match_with_vision("uploads/user_photo.jpg", candidates)
    assert result["catalog_entry_id"] == 1
    assert result["vision_confirmed"] is True


@pytest.mark.asyncio
async def test_vision_returns_none_match():
    candidates = [
        {"catalog_entry_id": 1, "canonical_name": "Mickey 50th", "image_path": "catalog_images/100.jpg", "visual_similarity": 0.78},
    ]
    mock_response = json.dumps({"best_match_catalog_entry_id": None, "confidence": "low", "reasoning": "None match"})
    with patch("src.pipeline.matching.send_vision_request", new_callable=AsyncMock, return_value=mock_response):
        result = await confirm_match_with_vision("uploads/user_photo.jpg", candidates)
    assert result is None


@pytest.mark.asyncio
async def test_vision_handles_api_error_gracefully():
    candidates = [
        {"catalog_entry_id": 1, "canonical_name": "Mickey 50th", "image_path": "catalog_images/100.jpg", "visual_similarity": 0.85},
    ]
    with patch("src.pipeline.matching.send_vision_request", new_callable=AsyncMock, side_effect=Exception("API error")):
        result = await confirm_match_with_vision("uploads/user_photo.jpg", candidates)
    assert result is None
