"""Tests for the PinTradingDB HTTP fetcher with rate limiting."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scraper.pintradingdb_fetcher import (
    download_pin_image,
    fetch_pin_detail,
    fetch_pin_list_page,
)
from scraper.pinpics_fetcher import RateLimiter


@pytest.mark.asyncio
async def test_returns_html_on_200():
    """fetch_pin_list_page returns HTML text on a 200 response."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "<html>Pin list page</html>"

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    limiter = RateLimiter(requests_per_second=100.0)

    with patch("scraper.pintradingdb_fetcher.httpx.AsyncClient", return_value=mock_client):
        result = await fetch_pin_list_page(page_number=1, limiter=limiter)

    assert result == "<html>Pin list page</html>"


@pytest.mark.asyncio
async def test_returns_none_on_404():
    """fetch_pin_detail returns None when the server responds with 404."""
    mock_response = MagicMock()
    mock_response.status_code = 404

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    limiter = RateLimiter(requests_per_second=100.0)

    with patch("scraper.pintradingdb_fetcher.httpx.AsyncClient", return_value=mock_client):
        result = await fetch_pin_detail(pin_id="99999", limiter=limiter)

    assert result is None


@pytest.mark.asyncio
async def test_saves_image_to_disk(tmp_path):
    """download_pin_image writes image bytes to disk and returns the file path."""
    fake_bytes = b"\x89PNG\r\n\x1a\n"  # minimal PNG header

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = fake_bytes

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    limiter = RateLimiter(requests_per_second=100.0)

    with patch("scraper.pintradingdb_fetcher.httpx.AsyncClient", return_value=mock_client):
        result = await download_pin_image(
            image_url="https://pintradingdb.com/images/pin_12345.png",
            pin_id="12345",
            output_dir=str(tmp_path),
            limiter=limiter,
        )

    assert result is not None
    assert result == str(tmp_path / "12345.png")
    assert (tmp_path / "12345.png").read_bytes() == fake_bytes


@pytest.mark.asyncio
async def test_returns_none_on_image_failure(tmp_path):
    """download_pin_image returns None on 404 and does not write a file."""
    mock_response = MagicMock()
    mock_response.status_code = 404

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    limiter = RateLimiter(requests_per_second=100.0)

    with patch("scraper.pintradingdb_fetcher.httpx.AsyncClient", return_value=mock_client):
        result = await download_pin_image(
            image_url="https://pintradingdb.com/images/missing.png",
            pin_id="00000",
            output_dir=str(tmp_path),
            limiter=limiter,
        )

    assert result is None
    assert not (tmp_path / "00000.png").exists()
