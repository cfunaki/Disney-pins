import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
from sqlalchemy import select
from src.models import Pin

# Import the CLI module by path since scripts/ isn't a package.
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "import_ebay_seller",
    Path(__file__).resolve().parents[1] / "scripts" / "import_ebay_seller.py",
)
import_ebay_seller = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(import_ebay_seller)  # type: ignore[union-attr]


def _mk_args(**overrides):
    defaults = dict(
        seller="pins-n-things",
        batch_name="pnt-test",
        query="disney",
        max=None,
        skip_processing=True,
        dry_run=False,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.mark.asyncio
async def test_run_creates_pins_from_seller_listings(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(import_ebay_seller, "UPLOAD_ROOT", tmp_path)

    summaries = [
        {"itemId": "v1|1|0", "title": "Lilo Stitch pin", "itemWebUrl": "https://ebay.com/1"},
        {"itemId": "v1|2|0", "title": "Maleficent LE 250", "itemWebUrl": "https://ebay.com/2"},
    ]

    async def fake_seller_search(seller, query="disney", limit=50, offset=0):
        return summaries if offset == 0 else []

    async def fake_item_detail(item_id):
        return {
            "itemId": item_id,
            "title": next(s["title"] for s in summaries if s["itemId"] == item_id),
            "description": "shipping boilerplate",
            "image": {"imageUrl": f"https://cdn/{item_id}.jpg"},
        }

    async def fake_download(url, dest):
        Path(dest).write_bytes(b"\xff\xd8\xff\xe0")  # tiny JPEG header
        return dest

    async def fake_parse(title, description):
        return {"characters": ["Stitch" if "Stitch" in title else "Maleficent"]}

    with patch.object(import_ebay_seller, "browse_api_seller_search", new=AsyncMock(side_effect=fake_seller_search)), \
         patch.object(import_ebay_seller, "browse_api_item_detail", new=AsyncMock(side_effect=fake_item_detail)), \
         patch.object(import_ebay_seller, "_download_image", new=AsyncMock(side_effect=fake_download)), \
         patch.object(import_ebay_seller, "parse_listing_label", new=AsyncMock(side_effect=fake_parse)):
        summary = await import_ebay_seller.run(
            _mk_args(), session_factory=lambda: db_session_wrapper(db_session),
        )

    assert summary["new"] == 2
    assert summary["refreshed"] == 0

    result = await db_session.execute(select(Pin).where(Pin.batch_id == "pnt-test"))
    pins = result.scalars().all()
    assert len(pins) == 2
    for pin in pins:
        assert pin.reference_source == "ebay_browse"
        assert pin.reference_external_id in {"v1|1|0", "v1|2|0"}
        assert pin.reference_raw_title.startswith(("Lilo", "Maleficent"))
        assert pin.reference_parsed_fields is not None
        assert len(pin.image_paths) == 1


@pytest.mark.asyncio
async def test_run_refreshes_parsed_fields_on_duplicate(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(import_ebay_seller, "UPLOAD_ROOT", tmp_path)

    existing = Pin(
        batch_id="pnt-test",
        image_paths=[str(tmp_path / "old.jpg")],
        reference_source="ebay_browse",
        reference_external_id="v1|1|0",
        reference_url="https://ebay.com/1",
        reference_raw_title="old title",
        reference_parsed_fields={"characters": ["Old"]},
        reference_ingested_at="2020-01-01T00:00:00",
    )
    db_session.add(existing)
    await db_session.commit()

    async def fake_seller_search(seller, query="disney", limit=50, offset=0):
        return [{"itemId": "v1|1|0", "title": "new title", "itemWebUrl": "https://ebay.com/1"}] if offset == 0 else []

    async def fake_item_detail(_):
        return {"title": "new title", "description": None, "image": {"imageUrl": "https://cdn/1.jpg"}}

    async def fake_parse(title, description):
        return {"characters": ["New"]}

    with patch.object(import_ebay_seller, "browse_api_seller_search", new=AsyncMock(side_effect=fake_seller_search)), \
         patch.object(import_ebay_seller, "browse_api_item_detail", new=AsyncMock(side_effect=fake_item_detail)), \
         patch.object(import_ebay_seller, "_download_image", new=AsyncMock()), \
         patch.object(import_ebay_seller, "parse_listing_label", new=AsyncMock(side_effect=fake_parse)):
        summary = await import_ebay_seller.run(
            _mk_args(), session_factory=lambda: db_session_wrapper(db_session),
        )

    assert summary["new"] == 0
    assert summary["refreshed"] == 1

    await db_session.refresh(existing)
    assert existing.reference_parsed_fields == {"characters": ["New"]}
    assert existing.reference_raw_title == "new title"
    # Image was NOT re-downloaded for a duplicate
    assert existing.image_paths == [str(tmp_path / "old.jpg")]


@pytest.mark.asyncio
async def test_run_dry_run_writes_nothing(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(import_ebay_seller, "UPLOAD_ROOT", tmp_path)

    async def fake_seller_search(seller, query="disney", limit=50, offset=0):
        return [{"itemId": "v1|1|0", "title": "x", "itemWebUrl": "https://ebay.com/1"}] if offset == 0 else []

    with patch.object(import_ebay_seller, "browse_api_seller_search", new=AsyncMock(side_effect=fake_seller_search)), \
         patch.object(import_ebay_seller, "browse_api_item_detail", new=AsyncMock(return_value={"title": "x", "image": {"imageUrl": "https://cdn/x.jpg"}})), \
         patch.object(import_ebay_seller, "_download_image", new=AsyncMock()) as dl, \
         patch.object(import_ebay_seller, "parse_listing_label", new=AsyncMock(return_value={})):
        summary = await import_ebay_seller.run(
            _mk_args(dry_run=True), session_factory=lambda: db_session_wrapper(db_session),
        )

    assert summary["dry_run"] is True
    dl.assert_not_called()
    result = await db_session.execute(select(Pin))
    assert result.scalars().all() == []


# --- session factory adapter so run() can reuse an existing db_session ---

from contextlib import asynccontextmanager

def db_session_wrapper(session):
    """Return an async context manager that yields the already-open test session."""
    @asynccontextmanager
    async def _cm():
        yield session
    return _cm()
