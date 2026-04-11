import json
from unittest.mock import AsyncMock, patch
import pytest

from src.pipeline.reference_label import parse_listing_label


def _fake_response(text_payload: str):
    class _Block:
        text = text_payload
    class _Resp:
        content = [_Block()]
    return _Resp()


@pytest.mark.asyncio
async def test_parser_returns_dict_on_valid_json():
    payload = {
        "characters": ["Lilo", "Stitch"],
        "franchise": "Lilo & Stitch",
        "series_or_collection": "Hidden Mickey Series 1",
        "release_year": 2019,
        "edition_size": 2000,
        "is_limited_edition": True,
        "confidence_notes": "clear title",
    }
    with patch(
        "src.pipeline.reference_label.client.messages.create",
        new=AsyncMock(return_value=_fake_response(json.dumps(payload))),
    ):
        result = await parse_listing_label(
            "Lilo Stitch LE 2000 Hidden Mickey Series 1 2019", None,
        )
    assert result == payload


@pytest.mark.asyncio
async def test_parser_omits_uncertain_fields():
    payload = {"characters": ["Maleficent"], "confidence_notes": "no year visible"}
    with patch(
        "src.pipeline.reference_label.client.messages.create",
        new=AsyncMock(return_value=_fake_response(json.dumps(payload))),
    ):
        result = await parse_listing_label("Maleficent pin", None)
    assert result == payload
    assert "release_year" not in result


@pytest.mark.asyncio
async def test_parser_returns_none_on_unparseable_json():
    mock = AsyncMock(return_value=_fake_response("not json at all"))
    with patch("src.pipeline.reference_label.client.messages.create", new=mock):
        result = await parse_listing_label("nonsense title", None)
    assert result is None
    assert mock.await_count == 1


@pytest.mark.asyncio
async def test_parser_retries_once_then_raises():
    mock = AsyncMock(side_effect=[RuntimeError("boom1"), RuntimeError("boom2")])
    with patch("src.pipeline.reference_label.client.messages.create", new=mock):
        with pytest.raises(RuntimeError):
            await parse_listing_label("any", None)
    assert mock.await_count == 2


@pytest.mark.asyncio
async def test_parser_retries_once_then_succeeds():
    payload = {"characters": ["Pluto"]}
    mock = AsyncMock(side_effect=[RuntimeError("boom"), _fake_response(json.dumps(payload))])
    with patch("src.pipeline.reference_label.client.messages.create", new=mock):
        result = await parse_listing_label("Pluto pin", None)
    assert result == payload
    assert mock.await_count == 2
