"""Tests for the PinPics HTTP fetcher with rate limiting."""

import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure the scripts directory is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from scraper.pinpics_fetcher import RateLimiter, fetch_pin_page


@pytest.mark.asyncio
async def test_rate_limiter_enforces_delay():
    """RateLimiter at 10 req/sec should enforce ~0.1s between calls."""
    limiter = RateLimiter(requests_per_second=10.0)

    start = time.monotonic()
    await limiter.acquire()
    await limiter.acquire()
    elapsed = time.monotonic() - start

    assert elapsed >= 0.09, f"Expected >= 0.09s elapsed, got {elapsed:.3f}s"


@pytest.mark.asyncio
async def test_fetch_pin_page_returns_html():
    """fetch_pin_page returns HTML text on a 200 response."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "<html>Pin page content</html>"

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    limiter = RateLimiter(requests_per_second=100.0)

    with patch("scraper.pinpics_fetcher.httpx.AsyncClient", return_value=mock_client):
        result = await fetch_pin_page(pin_id=12345, limiter=limiter)

    assert result == "<html>Pin page content</html>"


@pytest.mark.asyncio
async def test_fetch_pin_page_returns_none_on_404():
    """fetch_pin_page returns None when the server responds with 404."""
    mock_response = MagicMock()
    mock_response.status_code = 404

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    limiter = RateLimiter(requests_per_second=100.0)

    with patch("scraper.pinpics_fetcher.httpx.AsyncClient", return_value=mock_client):
        result = await fetch_pin_page(pin_id=99999, limiter=limiter)

    assert result is None
