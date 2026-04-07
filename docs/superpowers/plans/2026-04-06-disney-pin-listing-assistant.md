# Disney Pin Listing Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an MVP listing preparation tool that takes batch pin photos and produces reviewed, export-ready eBay listing drafts with AI identification, catalog matching, and comp-based pricing.

**Architecture:** Python FastAPI backend serving a simple HTML/JS frontend. Processing pipeline: image upload → Claude Sonnet vision extraction → catalog matching → eBay comp search → listing draft generation. SQLite database, local file storage, single user.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy, SQLite, Anthropic SDK, httpx (eBay API), Jinja2 (templates), pytest

---

## File Structure

```
disney-pin-assistant/
├── pyproject.toml                      # Project config, dependencies
├── .env.example                        # Template for API keys
├── .gitignore
├── src/
│   ├── __init__.py
│   ├── main.py                         # FastAPI app entry point, route mounting
│   ├── config.py                       # Settings (API keys, paths, concurrency)
│   ├── database.py                     # SQLAlchemy engine, session, Base
│   ├── models.py                       # All SQLAlchemy ORM models
│   ├── schemas.py                      # Pydantic request/response schemas
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── upload.py                   # Photo upload endpoints
│   │   ├── pins.py                     # Pin CRUD, status, review actions
│   │   ├── processing.py              # Batch processing trigger, progress
│   │   ├── export.py                   # CSV export endpoint
│   │   └── catalog.py                 # Catalog management endpoints
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── orchestrator.py            # Batch processing coordination, concurrency
│   │   ├── vision.py                  # Claude Sonnet vision extraction
│   │   ├── matching.py                # Catalog matching and ranking
│   │   ├── comps.py                   # eBay API comp search and filtering
│   │   └── listing.py                 # Listing draft generation
│   ├── services/
│   │   ├── __init__.py
│   │   ├── ebay_client.py             # eBay API authentication and requests
│   │   └── anthropic_client.py        # Anthropic API wrapper
│   └── templates/
│       ├── base.html                   # Base layout
│       ├── upload.html                 # Batch upload page
│       ├── queue.html                  # Review queue table
│       └── detail.html                # Pin detail/edit view
├── static/
│   ├── style.css
│   └── app.js                          # Frontend JS (upload, polling, editing)
├── uploads/                            # Uploaded pin photos (gitignored)
├── tests/
│   ├── __init__.py
│   ├── conftest.py                     # Fixtures: test DB, test client, sample data
│   ├── test_models.py                  # Database model tests
│   ├── test_vision.py                  # Vision extraction tests
│   ├── test_matching.py               # Catalog matching tests
│   ├── test_comps.py                  # Comp filtering tests
│   ├── test_listing.py                # Listing generation tests
│   ├── test_routes_upload.py          # Upload endpoint tests
│   ├── test_routes_pins.py            # Pin CRUD endpoint tests
│   ├── test_routes_processing.py      # Processing endpoint tests
│   └── test_routes_export.py          # Export endpoint tests
└── sample_data/                        # Sample pin photos for testing (gitignored)
```

---

### Task 1: Project Scaffolding

**Files:**
- Create: `disney-pin-assistant/pyproject.toml`
- Create: `disney-pin-assistant/.env.example`
- Create: `disney-pin-assistant/.gitignore`
- Create: `disney-pin-assistant/src/__init__.py`
- Create: `disney-pin-assistant/src/main.py`
- Create: `disney-pin-assistant/src/config.py`
- Create: `disney-pin-assistant/tests/__init__.py`

- [ ] **Step 1: Create project directory**

```bash
mkdir -p disney-pin-assistant/src/routes
mkdir -p disney-pin-assistant/src/pipeline
mkdir -p disney-pin-assistant/src/services
mkdir -p disney-pin-assistant/src/templates
mkdir -p disney-pin-assistant/static
mkdir -p disney-pin-assistant/uploads
mkdir -p disney-pin-assistant/sample_data
mkdir -p disney-pin-assistant/tests
```

- [ ] **Step 2: Create pyproject.toml**

```toml
[project]
name = "disney-pin-assistant"
version = "0.1.0"
description = "Disney pin listing preparation assistant"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "sqlalchemy>=2.0.0",
    "anthropic>=0.40.0",
    "httpx>=0.27.0",
    "python-multipart>=0.0.9",
    "python-dotenv>=1.0.0",
    "pydantic-settings>=2.0.0",
    "jinja2>=3.1.0",
    "aiosqlite>=0.20.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "httpx>=0.27.0",
]

[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.backends._legacy:_Backend"
```

- [ ] **Step 3: Create .env.example**

```
ANTHROPIC_API_KEY=your-key-here
EBAY_CLIENT_ID=your-client-id
EBAY_CLIENT_SECRET=your-client-secret
UPLOAD_DIR=./uploads
DATABASE_URL=sqlite+aiosqlite:///./pins.db
```

- [ ] **Step 4: Create .gitignore**

```
__pycache__/
*.pyc
.env
*.db
uploads/
sample_data/
.venv/
dist/
*.egg-info/
```

- [ ] **Step 5: Create src/config.py**

```python
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    ebay_client_id: str = ""
    ebay_client_secret: str = ""
    upload_dir: Path = Path("./uploads")
    database_url: str = "sqlite+aiosqlite:///./pins.db"
    max_concurrent_processing: int = 5

    model_config = {"env_file": ".env"}


settings = Settings()
```

- [ ] **Step 6: Create src/main.py**

```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Disney Pin Assistant")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 7: Create empty __init__.py files**

Create empty `__init__.py` in: `src/`, `src/routes/`, `src/pipeline/`, `src/services/`, `tests/`

- [ ] **Step 8: Install dependencies and verify**

```bash
cd disney-pin-assistant
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

- [ ] **Step 9: Verify the app starts**

```bash
cd disney-pin-assistant
uvicorn src.main:app --reload --port 8000
```

Visit `http://localhost:8000/health` — expected response: `{"status": "ok"}`

- [ ] **Step 10: Commit**

```bash
git add disney-pin-assistant/
git commit -m "feat: scaffold project with FastAPI, dependencies, and config"
```

---

### Task 2: Database Models

**Files:**
- Create: `disney-pin-assistant/src/database.py`
- Create: `disney-pin-assistant/src/models.py`
- Create: `disney-pin-assistant/tests/conftest.py`
- Create: `disney-pin-assistant/tests/test_models.py`

- [ ] **Step 1: Write the test for database models**

```python
# tests/test_models.py
import pytest
from sqlalchemy import select

from src.models import (
    Pin, PinStatus, VisionExtraction, CatalogEntry,
    CatalogMatch, MatchStatus, Comp, ListingType, MatchType,
    ListingDraft, ExportStatus,
)


@pytest.mark.asyncio
async def test_create_pin(db_session):
    pin = Pin(
        batch_id="batch-001",
        status=PinStatus.UNPROCESSED,
        photo_type="front",
        image_paths=["/uploads/pin1.jpg"],
    )
    db_session.add(pin)
    await db_session.commit()

    result = await db_session.execute(select(Pin))
    saved = result.scalar_one()
    assert saved.batch_id == "batch-001"
    assert saved.status == PinStatus.UNPROCESSED
    assert saved.image_paths == ["/uploads/pin1.jpg"]


@pytest.mark.asyncio
async def test_pin_status_transitions(db_session):
    pin = Pin(
        batch_id="batch-001",
        status=PinStatus.UNPROCESSED,
        image_paths=["/uploads/pin1.jpg"],
    )
    db_session.add(pin)
    await db_session.commit()

    pin.status = PinStatus.EXTRACTED
    await db_session.commit()

    result = await db_session.execute(select(Pin))
    saved = result.scalar_one()
    assert saved.status == PinStatus.EXTRACTED


@pytest.mark.asyncio
async def test_vision_extraction_relationship(db_session):
    pin = Pin(
        batch_id="batch-001",
        status=PinStatus.EXTRACTED,
        image_paths=["/uploads/pin1.jpg"],
    )
    db_session.add(pin)
    await db_session.flush()

    extraction = VisionExtraction(
        pin_id=pin.id,
        characters=["Mickey Mouse"],
        franchise="Mickey & Friends",
        pin_type="enamel",
        confidence_score=0.85,
        suggested_search_terms=["mickey mouse disney pin"],
    )
    db_session.add(extraction)
    await db_session.commit()

    result = await db_session.execute(
        select(VisionExtraction).where(VisionExtraction.pin_id == pin.id)
    )
    saved = result.scalar_one()
    assert saved.characters == ["Mickey Mouse"]
    assert saved.confidence_score == 0.85


@pytest.mark.asyncio
async def test_catalog_entry_and_match(db_session):
    pin = Pin(
        batch_id="batch-001",
        status=PinStatus.MATCHED,
        image_paths=["/uploads/pin1.jpg"],
    )
    db_session.add(pin)

    entry = CatalogEntry(
        canonical_name="Mickey Mouse Epcot Food & Wine 2019",
        characters=["Mickey Mouse"],
        franchise="Mickey & Friends",
        event="Epcot Food & Wine Festival",
        edition_size=3000,
        release_year=2019,
        pin_type="limited edition",
        source="pinpics",
        evidence_strength="high",
    )
    db_session.add(entry)
    await db_session.flush()

    match = CatalogMatch(
        pin_id=pin.id,
        catalog_entry_id=entry.id,
        match_confidence=0.9,
        match_reasoning="Character, event, and edition size all match",
        rank=1,
        status=MatchStatus.SUGGESTED,
    )
    db_session.add(match)
    await db_session.commit()

    result = await db_session.execute(
        select(CatalogMatch).where(CatalogMatch.pin_id == pin.id)
    )
    saved = result.scalar_one()
    assert saved.match_confidence == 0.9
    assert saved.rank == 1


@pytest.mark.asyncio
async def test_comp_creation(db_session):
    pin = Pin(
        batch_id="batch-001",
        status=PinStatus.PRICED,
        image_paths=["/uploads/pin1.jpg"],
    )
    db_session.add(pin)
    await db_session.flush()

    comp = Comp(
        pin_id=pin.id,
        ebay_listing_id="123456789",
        title="Mickey Mouse Food Wine 2019 Pin LE 3000",
        price=24.99,
        sale_date="2026-03-15",
        listing_type=ListingType.SOLD,
        condition="New",
        match_type=MatchType.EXACT,
        excluded=False,
    )
    db_session.add(comp)
    await db_session.commit()

    result = await db_session.execute(
        select(Comp).where(Comp.pin_id == pin.id)
    )
    saved = result.scalar_one()
    assert saved.price == 24.99
    assert saved.listing_type == ListingType.SOLD


@pytest.mark.asyncio
async def test_listing_draft_creation(db_session):
    pin = Pin(
        batch_id="batch-001",
        status=PinStatus.PRICED,
        image_paths=["/uploads/pin1.jpg"],
    )
    db_session.add(pin)
    await db_session.flush()

    draft = ListingDraft(
        pin_id=pin.id,
        title="Disney Mickey Mouse Epcot Food Wine 2019 Pin LE/3000",
        description="Limited edition Mickey Mouse pin from 2019 Epcot Food & Wine Festival.",
        suggested_price=24.99,
        quick_sale_price=19.99,
        price_confidence="medium",
        tags_keywords=["mickey mouse", "epcot", "food wine", "limited edition"],
        export_status=ExportStatus.DRAFT,
    )
    db_session.add(draft)
    await db_session.commit()

    result = await db_session.execute(
        select(ListingDraft).where(ListingDraft.pin_id == pin.id)
    )
    saved = result.scalar_one()
    assert saved.title.startswith("Disney Mickey")
    assert saved.export_status == ExportStatus.DRAFT
```

- [ ] **Step 2: Create test fixtures**

```python
# tests/conftest.py
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.models import Base


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd disney-pin-assistant
pytest tests/test_models.py -v
```

Expected: ImportError — `src.models` does not exist yet.

- [ ] **Step 4: Create src/database.py**

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with async_session() as session:
        yield session
```

- [ ] **Step 5: Create src/models.py**

```python
import enum
from datetime import datetime, timezone

from sqlalchemy import String, Float, Integer, Boolean, Text, Enum, ForeignKey, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class PinStatus(str, enum.Enum):
    UNPROCESSED = "unprocessed"
    EXTRACTED = "extracted"
    MATCHED = "matched"
    PRICED = "priced"
    APPROVED = "approved"
    EXPORTED = "exported"


class MatchStatus(str, enum.Enum):
    SUGGESTED = "suggested"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ListingType(str, enum.Enum):
    SOLD = "sold"
    ACTIVE = "active"


class MatchType(str, enum.Enum):
    EXACT = "exact"
    NEAR = "near"


class ExportStatus(str, enum.Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    EXPORTED = "exported"


class Pin(Base):
    __tablename__ = "pins"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(100))
    status: Mapped[PinStatus] = mapped_column(Enum(PinStatus), default=PinStatus.UNPROCESSED)
    photo_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    seller_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_paths: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    extraction: Mapped["VisionExtraction | None"] = relationship(back_populates="pin")
    catalog_matches: Mapped[list["CatalogMatch"]] = relationship(back_populates="pin")
    comps: Mapped[list["Comp"]] = relationship(back_populates="pin")
    listing_draft: Mapped["ListingDraft | None"] = relationship(back_populates="pin")


class VisionExtraction(Base):
    __tablename__ = "vision_extractions"

    id: Mapped[int] = mapped_column(primary_key=True)
    pin_id: Mapped[int] = mapped_column(ForeignKey("pins.id"))
    characters: Mapped[list] = mapped_column(JSON, default=list)
    franchise: Mapped[str | None] = mapped_column(String(200), nullable=True)
    collection_or_series: Mapped[str | None] = mapped_column(String(200), nullable=True)
    text_on_pin: Mapped[str | None] = mapped_column(Text, nullable=True)
    visible_dates: Mapped[str | None] = mapped_column(String(200), nullable=True)
    event_clues: Mapped[str | None] = mapped_column(Text, nullable=True)
    pin_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    edition_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    condition_observations: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_search_terms: Mapped[list] = mapped_column(JSON, default=list)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    raw_api_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))

    pin: Mapped["Pin"] = relationship(back_populates="extraction")


class CatalogEntry(Base):
    __tablename__ = "catalog_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(500))
    alternate_names: Mapped[list] = mapped_column(JSON, default=list)
    characters: Mapped[list] = mapped_column(JSON, default=list)
    franchise: Mapped[str | None] = mapped_column(String(200), nullable=True)
    series_or_collection: Mapped[str | None] = mapped_column(String(200), nullable=True)
    event: Mapped[str | None] = mapped_column(String(200), nullable=True)
    edition_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    release_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pin_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    exclusive_source: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_reference_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reference_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    evidence_strength: Mapped[str] = mapped_column(String(20), default="low")
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    matches: Mapped[list["CatalogMatch"]] = relationship(back_populates="catalog_entry")


class CatalogMatch(Base):
    __tablename__ = "catalog_matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    pin_id: Mapped[int] = mapped_column(ForeignKey("pins.id"))
    catalog_entry_id: Mapped[int] = mapped_column(ForeignKey("catalog_entries.id"))
    match_confidence: Mapped[float] = mapped_column(Float)
    match_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    rank: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[MatchStatus] = mapped_column(Enum(MatchStatus), default=MatchStatus.SUGGESTED)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))

    pin: Mapped["Pin"] = relationship(back_populates="catalog_matches")
    catalog_entry: Mapped["CatalogEntry"] = relationship(back_populates="matches")


class Comp(Base):
    __tablename__ = "comps"

    id: Mapped[int] = mapped_column(primary_key=True)
    pin_id: Mapped[int] = mapped_column(ForeignKey("pins.id"))
    ebay_listing_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    title: Mapped[str] = mapped_column(String(500))
    price: Mapped[float] = mapped_column(Float)
    sale_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    listing_type: Mapped[ListingType] = mapped_column(Enum(ListingType))
    condition: Mapped[str | None] = mapped_column(String(50), nullable=True)
    match_type: Mapped[MatchType] = mapped_column(Enum(MatchType), default=MatchType.NEAR)
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    exclusion_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    raw_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))

    pin: Mapped["Pin"] = relationship(back_populates="comps")


class ListingDraft(Base):
    __tablename__ = "listing_drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    pin_id: Mapped[int] = mapped_column(ForeignKey("pins.id"))
    title: Mapped[str] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    item_specifics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    suggested_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    quick_sale_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_confidence: Mapped[str] = mapped_column(String(20), default="low")
    pricing_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_suggestion: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tags_keywords: Mapped[list] = mapped_column(JSON, default=list)
    export_status: Mapped[ExportStatus] = mapped_column(Enum(ExportStatus), default=ExportStatus.DRAFT)
    seller_edits: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    pin: Mapped["Pin"] = relationship(back_populates="listing_draft")
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd disney-pin-assistant
pytest tests/test_models.py -v
```

Expected: All 6 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add disney-pin-assistant/src/database.py disney-pin-assistant/src/models.py disney-pin-assistant/tests/conftest.py disney-pin-assistant/tests/test_models.py
git commit -m "feat: add database models for pins, extractions, catalog, comps, drafts"
```

---

### Task 3: Pydantic Schemas

**Files:**
- Create: `disney-pin-assistant/src/schemas.py`

- [ ] **Step 1: Create src/schemas.py**

```python
from pydantic import BaseModel


class PinUploadResponse(BaseModel):
    id: int
    batch_id: str
    status: str
    photo_type: str | None
    image_paths: list[str]


class VisionExtractionResponse(BaseModel):
    characters: list[str]
    franchise: str | None
    collection_or_series: str | None
    text_on_pin: str | None
    visible_dates: str | None
    event_clues: str | None
    pin_type: str | None
    edition_size: int | None
    condition_observations: str | None
    suggested_search_terms: list[str]
    confidence_score: float


class CatalogEntryResponse(BaseModel):
    id: int
    canonical_name: str
    characters: list[str]
    franchise: str | None
    series_or_collection: str | None
    event: str | None
    edition_size: int | None
    release_year: int | None
    pin_type: str | None
    evidence_strength: str


class CatalogMatchResponse(BaseModel):
    catalog_entry: CatalogEntryResponse
    match_confidence: float
    match_reasoning: str | None
    rank: int
    status: str


class CompResponse(BaseModel):
    ebay_listing_id: str | None
    title: str
    price: float
    sale_date: str | None
    listing_type: str
    condition: str | None
    match_type: str
    excluded: bool
    exclusion_reason: str | None


class ListingDraftResponse(BaseModel):
    title: str
    description: str | None
    item_specifics: dict | None
    suggested_price: float | None
    quick_sale_price: float | None
    price_confidence: str
    pricing_reasoning: str | None
    tags_keywords: list[str]
    export_status: str


class PinDetailResponse(BaseModel):
    id: int
    batch_id: str
    status: str
    photo_type: str | None
    seller_notes: str | None
    image_paths: list[str]
    extraction: VisionExtractionResponse | None
    catalog_matches: list[CatalogMatchResponse]
    comps: list[CompResponse]
    listing_draft: ListingDraftResponse | None


class PinUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    suggested_price: float | None = None
    tags_keywords: list[str] | None = None
    seller_notes: str | None = None


class BatchProcessRequest(BaseModel):
    batch_id: str


class BatchProgressResponse(BaseModel):
    batch_id: str
    total: int
    processed: int
    status_counts: dict[str, int]
```

- [ ] **Step 2: Commit**

```bash
git add disney-pin-assistant/src/schemas.py
git commit -m "feat: add Pydantic request/response schemas"
```

---

### Task 4: Upload Endpoint

**Files:**
- Create: `disney-pin-assistant/src/routes/upload.py`
- Create: `disney-pin-assistant/src/routes/__init__.py`
- Modify: `disney-pin-assistant/src/main.py`
- Create: `disney-pin-assistant/tests/test_routes_upload.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_routes_upload.py
import io
import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app
from src.database import get_db
from src.models import Base

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession


@pytest.fixture
async def test_app():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield app
    app.dependency_overrides.clear()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_upload_single_photo(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        fake_image = io.BytesIO(b"fake image data")
        response = await client.post(
            "/api/upload",
            files=[("files", ("pin1.jpg", fake_image, "image/jpeg"))],
            data={"photo_type": "front"},
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data["pins"]) == 1
    assert data["pins"][0]["status"] == "unprocessed"
    assert data["batch_id"] is not None


@pytest.mark.asyncio
async def test_upload_multiple_photos(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        files = [
            ("files", ("pin1.jpg", io.BytesIO(b"img1"), "image/jpeg")),
            ("files", ("pin2.jpg", io.BytesIO(b"img2"), "image/jpeg")),
            ("files", ("pin3.jpg", io.BytesIO(b"img3"), "image/jpeg")),
        ]
        response = await client.post("/api/upload", files=files)

    assert response.status_code == 200
    data = response.json()
    assert len(data["pins"]) == 3
    assert all(p["status"] == "unprocessed" for p in data["pins"])
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd disney-pin-assistant
pytest tests/test_routes_upload.py -v
```

Expected: FAIL — route not found.

- [ ] **Step 3: Create src/routes/__init__.py (empty file)**

- [ ] **Step 4: Create src/routes/upload.py**

```python
import uuid
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Form, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import get_db
from src.models import Pin, PinStatus

router = APIRouter(prefix="/api")


@router.post("/upload")
async def upload_photos(
    files: list[UploadFile] = File(...),
    photo_type: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    batch_id = str(uuid.uuid4())[:8]
    upload_dir = settings.upload_dir / batch_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    pins = []
    for file in files:
        file_path = upload_dir / file.filename
        content = await file.read()
        file_path.write_bytes(content)

        pin = Pin(
            batch_id=batch_id,
            status=PinStatus.UNPROCESSED,
            photo_type=photo_type,
            image_paths=[str(file_path)],
        )
        db.add(pin)
        await db.flush()

        pins.append({
            "id": pin.id,
            "batch_id": pin.batch_id,
            "status": pin.status.value,
            "photo_type": pin.photo_type,
            "image_paths": pin.image_paths,
        })

    await db.commit()
    return {"batch_id": batch_id, "pins": pins}
```

- [ ] **Step 5: Mount the router in main.py**

```python
# src/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.database import engine
from src.models import Base
from src.routes.upload import router as upload_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="Disney Pin Assistant", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(upload_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd disney-pin-assistant
pytest tests/test_routes_upload.py -v
```

Expected: All 2 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add disney-pin-assistant/src/routes/ disney-pin-assistant/src/main.py disney-pin-assistant/tests/test_routes_upload.py
git commit -m "feat: add photo upload endpoint with batch grouping"
```

---

### Task 5: Vision Extraction Pipeline

**Files:**
- Create: `disney-pin-assistant/src/services/anthropic_client.py`
- Create: `disney-pin-assistant/src/services/__init__.py`
- Create: `disney-pin-assistant/src/pipeline/vision.py`
- Create: `disney-pin-assistant/src/pipeline/__init__.py`
- Create: `disney-pin-assistant/tests/test_vision.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vision.py
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
    assert len(call_args[0][0]) == 2  # Two image paths passed
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd disney-pin-assistant
pytest tests/test_vision.py -v
```

Expected: FAIL — module not found.

- [ ] **Step 3: Create src/services/__init__.py (empty file)**

- [ ] **Step 4: Create src/services/anthropic_client.py**

```python
import base64
from pathlib import Path

import anthropic

from src.config import settings

client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


async def send_vision_request(image_paths: list[str], prompt: str) -> dict:
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
```

- [ ] **Step 5: Create src/pipeline/__init__.py (empty file)**

- [ ] **Step 6: Create src/pipeline/vision.py**

```python
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
    # Strip markdown code fences if present
    text = raw_response.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[:-3]
    return json.loads(text.strip())


async def extract_pin_metadata(image_paths: list[str]) -> dict:
    return await call_vision_api(image_paths)
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
cd disney-pin-assistant
pytest tests/test_vision.py -v
```

Expected: All 3 tests PASS.

- [ ] **Step 8: Commit**

```bash
git add disney-pin-assistant/src/services/ disney-pin-assistant/src/pipeline/vision.py disney-pin-assistant/src/pipeline/__init__.py disney-pin-assistant/tests/test_vision.py
git commit -m "feat: add Claude vision extraction pipeline with structured JSON output"
```

---

### Task 6: Catalog Matching

**Files:**
- Create: `disney-pin-assistant/src/pipeline/matching.py`
- Create: `disney-pin-assistant/tests/test_matching.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_matching.py
import pytest
from sqlalchemy import select

from src.models import Base, CatalogEntry, CatalogMatch
from src.pipeline.matching import find_catalog_matches


@pytest.fixture
async def seeded_db(db_session):
    entries = [
        CatalogEntry(
            canonical_name="Mickey Mouse Epcot Food & Wine 2019 LE 3000",
            characters=["Mickey Mouse"],
            franchise="Mickey & Friends",
            event="Epcot Food & Wine Festival",
            edition_size=3000,
            release_year=2019,
            pin_type="limited edition",
            source="pinpics",
            evidence_strength="high",
        ),
        CatalogEntry(
            canonical_name="Mickey Mouse Classic Pose Pin",
            characters=["Mickey Mouse"],
            franchise="Mickey & Friends",
            pin_type="rack",
            source="pinpics",
            evidence_strength="medium",
        ),
        CatalogEntry(
            canonical_name="Stitch Surfing Pin",
            characters=["Stitch"],
            franchise="Lilo & Stitch",
            pin_type="enamel",
            source="pinpics",
            evidence_strength="medium",
        ),
    ]
    db_session.add_all(entries)
    await db_session.commit()
    return db_session


@pytest.mark.asyncio
async def test_find_matches_exact(seeded_db):
    extraction = {
        "characters": ["Mickey Mouse"],
        "franchise": "Mickey & Friends",
        "event_clues": "Food & Wine Festival",
        "edition_size": 3000,
        "pin_type": "limited edition",
        "text_on_pin": None,
        "collection_or_series": None,
        "visible_dates": "2019",
        "suggested_search_terms": [],
    }

    matches = await find_catalog_matches(seeded_db, extraction, max_results=3)

    assert len(matches) >= 1
    assert matches[0]["canonical_name"] == "Mickey Mouse Epcot Food & Wine 2019 LE 3000"
    assert matches[0]["confidence"] > 0.7


@pytest.mark.asyncio
async def test_find_matches_partial(seeded_db):
    extraction = {
        "characters": ["Mickey Mouse"],
        "franchise": "Mickey & Friends",
        "event_clues": None,
        "edition_size": None,
        "pin_type": "rack",
        "text_on_pin": None,
        "collection_or_series": None,
        "visible_dates": None,
        "suggested_search_terms": [],
    }

    matches = await find_catalog_matches(seeded_db, extraction, max_results=3)

    assert len(matches) >= 1
    # Should match the rack pin higher than the LE pin
    rack_match = next(m for m in matches if "Classic Pose" in m["canonical_name"])
    le_match = next(m for m in matches if "Food & Wine" in m["canonical_name"])
    assert rack_match["confidence"] >= le_match["confidence"]


@pytest.mark.asyncio
async def test_find_matches_no_results(seeded_db):
    extraction = {
        "characters": ["Elsa"],
        "franchise": "Frozen",
        "event_clues": None,
        "edition_size": None,
        "pin_type": "enamel",
        "text_on_pin": None,
        "collection_or_series": None,
        "visible_dates": None,
        "suggested_search_terms": [],
    }

    matches = await find_catalog_matches(seeded_db, extraction, max_results=3)

    assert len(matches) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd disney-pin-assistant
pytest tests/test_matching.py -v
```

Expected: FAIL — module not found.

- [ ] **Step 3: Create src/pipeline/matching.py**

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import CatalogEntry


async def find_catalog_matches(
    db: AsyncSession,
    extraction: dict,
    max_results: int = 3,
) -> list[dict]:
    result = await db.execute(select(CatalogEntry))
    all_entries = result.scalars().all()

    scored = []
    for entry in all_entries:
        score = _compute_match_score(entry, extraction)
        if score > 0:
            scored.append({
                "catalog_entry_id": entry.id,
                "canonical_name": entry.canonical_name,
                "characters": entry.characters,
                "franchise": entry.franchise,
                "event": entry.event,
                "edition_size": entry.edition_size,
                "release_year": entry.release_year,
                "pin_type": entry.pin_type,
                "evidence_strength": entry.evidence_strength,
                "confidence": score,
                "reasoning": _build_reasoning(entry, extraction),
            })

    scored.sort(key=lambda x: x["confidence"], reverse=True)
    return scored[:max_results]


def _compute_match_score(entry: CatalogEntry, extraction: dict) -> float:
    score = 0.0
    max_score = 0.0

    # Character overlap (weight: 3)
    max_score += 3
    extracted_chars = {c.lower() for c in (extraction.get("characters") or [])}
    entry_chars = {c.lower() for c in (entry.characters or [])}
    if extracted_chars and entry_chars:
        overlap = len(extracted_chars & entry_chars)
        total = len(extracted_chars | entry_chars)
        if total > 0:
            score += 3 * (overlap / total)

    # Franchise match (weight: 2)
    max_score += 2
    if extraction.get("franchise") and entry.franchise:
        if extraction["franchise"].lower() == entry.franchise.lower():
            score += 2

    # Event match (weight: 4 — high specificity)
    max_score += 4
    event_clues = extraction.get("event_clues") or ""
    if event_clues and entry.event:
        event_words = set(event_clues.lower().split())
        entry_event_words = set(entry.event.lower().split())
        common = event_words & entry_event_words
        if len(common) >= 2:
            score += 4
        elif len(common) == 1:
            score += 2

    # Edition size match (weight: 3 — very specific)
    max_score += 3
    if extraction.get("edition_size") and entry.edition_size:
        if extraction["edition_size"] == entry.edition_size:
            score += 3

    # Pin type match (weight: 1)
    max_score += 1
    if extraction.get("pin_type") and entry.pin_type:
        if extraction["pin_type"].lower() == entry.pin_type.lower():
            score += 1

    # Year match (weight: 2)
    max_score += 2
    visible_dates = extraction.get("visible_dates") or ""
    if visible_dates and entry.release_year:
        if str(entry.release_year) in visible_dates:
            score += 2

    if max_score == 0:
        return 0.0

    normalized = score / max_score

    # Require minimum threshold
    if normalized < 0.2:
        return 0.0

    return round(normalized, 2)


def _build_reasoning(entry: CatalogEntry, extraction: dict) -> str:
    reasons = []
    extracted_chars = {c.lower() for c in (extraction.get("characters") or [])}
    entry_chars = {c.lower() for c in (entry.characters or [])}

    if extracted_chars & entry_chars:
        reasons.append(f"Character match: {', '.join(extracted_chars & entry_chars)}")

    if extraction.get("franchise") and entry.franchise:
        if extraction["franchise"].lower() == entry.franchise.lower():
            reasons.append(f"Franchise match: {entry.franchise}")

    event_clues = extraction.get("event_clues") or ""
    if event_clues and entry.event:
        reasons.append(f"Event match: {entry.event}")

    if extraction.get("edition_size") and entry.edition_size:
        if extraction["edition_size"] == entry.edition_size:
            reasons.append(f"Edition size match: {entry.edition_size}")

    if extraction.get("pin_type") and entry.pin_type:
        if extraction["pin_type"].lower() == entry.pin_type.lower():
            reasons.append(f"Pin type match: {entry.pin_type}")

    return "; ".join(reasons) if reasons else "Weak match"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd disney-pin-assistant
pytest tests/test_matching.py -v
```

Expected: All 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add disney-pin-assistant/src/pipeline/matching.py disney-pin-assistant/tests/test_matching.py
git commit -m "feat: add catalog matching with weighted attribute scoring"
```

---

### Task 7: eBay Comp Search

**Files:**
- Create: `disney-pin-assistant/src/services/ebay_client.py`
- Create: `disney-pin-assistant/src/pipeline/comps.py`
- Create: `disney-pin-assistant/tests/test_comps.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_comps.py
import pytest
from unittest.mock import AsyncMock, patch

from src.pipeline.comps import search_comps, filter_comps


@pytest.mark.asyncio
async def test_search_comps():
    mock_items = [
        {
            "itemId": "111",
            "title": "Mickey Mouse Food Wine 2019 Pin LE 3000",
            "price": {"value": "24.99", "currency": "USD"},
            "condition": "New",
            "itemEndDate": "2026-03-15",
        },
        {
            "itemId": "222",
            "title": "Mickey Mouse Pin Lot of 10",
            "price": {"value": "45.00", "currency": "USD"},
            "condition": "Used",
            "itemEndDate": "2026-03-10",
        },
    ]

    with patch("src.pipeline.comps.ebay_search", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = mock_items
        results = await search_comps(
            search_terms=["mickey mouse food wine 2019 pin le 3000"],
            listing_type="sold",
        )

    assert len(results) == 2
    assert results[0]["ebay_listing_id"] == "111"
    assert results[0]["price"] == 24.99


def test_filter_comps_excludes_lots():
    comps = [
        {"title": "Mickey Mouse Food Wine 2019 Pin LE 3000", "price": 24.99, "excluded": False, "exclusion_reason": None},
        {"title": "Mickey Mouse Pin Lot of 10 Disney Pins", "price": 45.00, "excluded": False, "exclusion_reason": None},
        {"title": "Disney Pin Bundle 20 Random Pins", "price": 30.00, "excluded": False, "exclusion_reason": None},
    ]

    filtered = filter_comps(comps)

    included = [c for c in filtered if not c["excluded"]]
    excluded = [c for c in filtered if c["excluded"]]

    assert len(included) == 1
    assert included[0]["title"] == "Mickey Mouse Food Wine 2019 Pin LE 3000"
    assert len(excluded) == 2
    assert all("lot" in c["exclusion_reason"].lower() or "bundle" in c["exclusion_reason"].lower() for c in excluded)


def test_filter_comps_keeps_singles():
    comps = [
        {"title": "Stitch Surfing Disney Pin", "price": 12.00, "excluded": False, "exclusion_reason": None},
        {"title": "Mickey Mouse Classic Pin", "price": 8.00, "excluded": False, "exclusion_reason": None},
    ]

    filtered = filter_comps(comps)

    assert all(not c["excluded"] for c in filtered)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd disney-pin-assistant
pytest tests/test_comps.py -v
```

Expected: FAIL — module not found.

- [ ] **Step 3: Create src/services/ebay_client.py**

```python
import httpx

from src.config import settings

_token_cache: dict = {"access_token": None}


async def get_ebay_token() -> str:
    if _token_cache["access_token"]:
        return _token_cache["access_token"]

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.ebay.com/identity/v1/oauth2/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            auth=(settings.ebay_client_id, settings.ebay_client_secret),
            data={
                "grant_type": "client_credentials",
                "scope": "https://api.ebay.com/oauth/api_scope",
            },
        )
        response.raise_for_status()
        data = response.json()
        _token_cache["access_token"] = data["access_token"]
        return data["access_token"]


async def browse_api_search(query: str, filters: str | None = None, limit: int = 50) -> list[dict]:
    token = await get_ebay_token()
    params = {"q": query, "limit": str(limit)}
    if filters:
        params["filter"] = filters

    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.ebay.com/buy/browse/v1/item_summary/search",
            headers={
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
            },
            params=params,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("itemSummaries", [])
```

- [ ] **Step 4: Create src/pipeline/comps.py**

```python
import re

from src.services.ebay_client import browse_api_search

LOT_BUNDLE_PATTERNS = [
    re.compile(r"\blot\b", re.IGNORECASE),
    re.compile(r"\blots\b", re.IGNORECASE),
    re.compile(r"\bbundle\b", re.IGNORECASE),
    re.compile(r"\bset of \d+\b", re.IGNORECASE),
    re.compile(r"\b\d+ pins\b", re.IGNORECASE),
    re.compile(r"\b\d+ pin lot\b", re.IGNORECASE),
]


async def ebay_search(search_terms: list[str], listing_type: str) -> list[dict]:
    query = " ".join(search_terms)

    filters = "categoryId:171"  # Disney Pins category
    if listing_type == "sold":
        filters += ",buyingOptions:{FIXED_PRICE}"

    return await browse_api_search(query, filters=filters)


async def search_comps(search_terms: list[str], listing_type: str = "sold") -> list[dict]:
    raw_items = await ebay_search(search_terms, listing_type)

    comps = []
    for item in raw_items:
        price_info = item.get("price", {})
        price = float(price_info.get("value", 0))

        comps.append({
            "ebay_listing_id": item.get("itemId"),
            "title": item.get("title", ""),
            "price": price,
            "sale_date": item.get("itemEndDate"),
            "listing_type": listing_type,
            "condition": item.get("condition"),
            "excluded": False,
            "exclusion_reason": None,
            "raw_data": item,
        })

    return comps


def filter_comps(comps: list[dict]) -> list[dict]:
    for comp in comps:
        title = comp.get("title", "")
        for pattern in LOT_BUNDLE_PATTERNS:
            if pattern.search(title):
                comp["excluded"] = True
                comp["exclusion_reason"] = f"Detected as lot/bundle: matched '{pattern.pattern}'"
                break

    return comps
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd disney-pin-assistant
pytest tests/test_comps.py -v
```

Expected: All 3 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add disney-pin-assistant/src/services/ebay_client.py disney-pin-assistant/src/pipeline/comps.py disney-pin-assistant/tests/test_comps.py
git commit -m "feat: add eBay comp search with lot/bundle filtering"
```

---

### Task 8: Listing Draft Generation

**Files:**
- Create: `disney-pin-assistant/src/pipeline/listing.py`
- Create: `disney-pin-assistant/tests/test_listing.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_listing.py
import pytest

from src.pipeline.listing import generate_listing_draft, compute_pricing


def test_generate_listing_draft():
    extraction = {
        "characters": ["Mickey Mouse"],
        "franchise": "Mickey & Friends",
        "event_clues": "Epcot Food & Wine Festival",
        "pin_type": "limited edition",
        "edition_size": 3000,
        "condition_observations": "Excellent condition",
        "visible_dates": "2019",
        "text_on_pin": "Walt Disney World",
        "collection_or_series": None,
        "suggested_search_terms": ["mickey mouse food wine pin"],
    }
    catalog_match = {
        "canonical_name": "Mickey Mouse Epcot Food & Wine 2019 LE 3000",
        "characters": ["Mickey Mouse"],
        "franchise": "Mickey & Friends",
        "event": "Epcot Food & Wine Festival",
        "edition_size": 3000,
        "release_year": 2019,
        "pin_type": "limited edition",
    }

    draft = generate_listing_draft(extraction, catalog_match, pricing=None)

    assert len(draft["title"]) <= 80
    assert "Mickey Mouse" in draft["title"]
    assert draft["description"] is not None
    assert len(draft["tags_keywords"]) > 0


def test_generate_listing_draft_no_match():
    extraction = {
        "characters": ["Stitch"],
        "franchise": "Lilo & Stitch",
        "event_clues": None,
        "pin_type": "enamel",
        "edition_size": None,
        "condition_observations": "Good condition",
        "visible_dates": None,
        "text_on_pin": "Disney Parks",
        "collection_or_series": None,
        "suggested_search_terms": ["stitch disney parks pin"],
    }

    draft = generate_listing_draft(extraction, catalog_match=None, pricing=None)

    assert len(draft["title"]) <= 80
    assert "Stitch" in draft["title"]
    assert draft["description"] is not None


def test_compute_pricing():
    comps = [
        {"price": 20.00, "listing_type": "sold", "excluded": False, "match_type": "exact"},
        {"price": 25.00, "listing_type": "sold", "excluded": False, "match_type": "exact"},
        {"price": 30.00, "listing_type": "sold", "excluded": False, "match_type": "exact"},
        {"price": 100.00, "listing_type": "sold", "excluded": True, "match_type": "exact"},
    ]

    pricing = compute_pricing(comps)

    assert pricing["suggested_price"] == 25.00  # median of non-excluded
    assert pricing["quick_sale_price"] == 20.00  # low end
    assert pricing["price_confidence"] == "medium"
    assert pricing["comp_count"] == 3


def test_compute_pricing_no_comps():
    pricing = compute_pricing([])

    assert pricing["suggested_price"] is None
    assert pricing["quick_sale_price"] is None
    assert pricing["price_confidence"] == "low"
    assert pricing["comp_count"] == 0


def test_compute_pricing_high_confidence():
    comps = [
        {"price": p, "listing_type": "sold", "excluded": False, "match_type": "exact"}
        for p in [22, 23, 24, 25, 24, 23, 25, 24]
    ]

    pricing = compute_pricing(comps)

    assert pricing["price_confidence"] == "high"
    assert pricing["comp_count"] == 8
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd disney-pin-assistant
pytest tests/test_listing.py -v
```

Expected: FAIL — module not found.

- [ ] **Step 3: Create src/pipeline/listing.py**

```python
import statistics


def generate_listing_draft(
    extraction: dict,
    catalog_match: dict | None,
    pricing: dict | None,
) -> dict:
    title = _build_title(extraction, catalog_match)
    description = _build_description(extraction, catalog_match)
    tags = _build_tags(extraction)

    draft = {
        "title": title[:80],
        "description": description,
        "item_specifics": _build_item_specifics(extraction, catalog_match),
        "suggested_price": pricing["suggested_price"] if pricing else None,
        "quick_sale_price": pricing["quick_sale_price"] if pricing else None,
        "price_confidence": pricing["price_confidence"] if pricing else "low",
        "pricing_reasoning": pricing.get("reasoning") if pricing else None,
        "tags_keywords": tags,
        "export_status": "draft",
    }

    return draft


def _build_title(extraction: dict, catalog_match: dict | None) -> str:
    parts = ["Disney"]

    characters = extraction.get("characters") or []
    if characters:
        parts.append(" ".join(characters[:2]))

    event = None
    if catalog_match and catalog_match.get("event"):
        event = catalog_match["event"]
    elif extraction.get("event_clues"):
        event = extraction["event_clues"]

    if event:
        parts.append(event)

    year = None
    if catalog_match and catalog_match.get("release_year"):
        year = str(catalog_match["release_year"])
    elif extraction.get("visible_dates"):
        year = extraction["visible_dates"]

    if year:
        parts.append(year)

    parts.append("Pin")

    pin_type = extraction.get("pin_type", "")
    edition = extraction.get("edition_size")
    if pin_type == "limited edition" and edition:
        parts.append(f"LE/{edition}")
    elif pin_type == "limited edition":
        parts.append("LE")

    return " ".join(parts)


def _build_description(extraction: dict, catalog_match: dict | None) -> str:
    lines = []

    name = ""
    if catalog_match:
        name = catalog_match.get("canonical_name", "")
    if not name:
        chars = ", ".join(extraction.get("characters") or ["Unknown"])
        name = f"{chars} Disney Pin"

    lines.append(name)

    pin_type = extraction.get("pin_type")
    edition = extraction.get("edition_size")
    if pin_type:
        type_line = f"Type: {pin_type}"
        if edition:
            type_line += f" (edition size: {edition})"
        lines.append(type_line)

    event = extraction.get("event_clues")
    if event:
        lines.append(f"Event: {event}")

    condition = extraction.get("condition_observations")
    if condition:
        lines.append(f"Condition: {condition}")

    return "\n".join(lines)


def _build_tags(extraction: dict) -> list[str]:
    tags = set()

    for char in extraction.get("characters") or []:
        tags.add(char.lower())

    franchise = extraction.get("franchise")
    if franchise:
        tags.add(franchise.lower())

    pin_type = extraction.get("pin_type")
    if pin_type:
        tags.add(pin_type.lower())

    event = extraction.get("event_clues")
    if event:
        tags.add(event.lower())

    tags.add("disney pin")

    return sorted(tags)


def _build_item_specifics(extraction: dict, catalog_match: dict | None) -> dict:
    specifics = {"Brand": "Disney"}

    characters = extraction.get("characters") or []
    if characters:
        specifics["Character"] = ", ".join(characters)

    franchise = extraction.get("franchise")
    if franchise:
        specifics["Franchise"] = franchise

    pin_type = extraction.get("pin_type")
    if pin_type:
        specifics["Type"] = pin_type

    edition = extraction.get("edition_size")
    if edition:
        specifics["Edition Size"] = str(edition)

    year = None
    if catalog_match and catalog_match.get("release_year"):
        year = catalog_match["release_year"]
    if year:
        specifics["Year"] = str(year)

    return specifics


def compute_pricing(comps: list[dict]) -> dict:
    valid_comps = [
        c for c in comps
        if not c.get("excluded") and c.get("listing_type") == "sold"
    ]

    if not valid_comps:
        return {
            "suggested_price": None,
            "quick_sale_price": None,
            "price_confidence": "low",
            "comp_count": 0,
            "reasoning": "No valid sold comps found",
        }

    prices = sorted(c["price"] for c in valid_comps)
    median_price = round(statistics.median(prices), 2)
    low_price = round(prices[0], 2)

    comp_count = len(valid_comps)

    if comp_count >= 5:
        confidence = "high"
    elif comp_count >= 2:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "suggested_price": median_price,
        "quick_sale_price": low_price,
        "price_confidence": confidence,
        "comp_count": comp_count,
        "reasoning": f"Based on {comp_count} sold comps. Range: ${low_price}-${prices[-1]:.2f}, Median: ${median_price}",
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd disney-pin-assistant
pytest tests/test_listing.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add disney-pin-assistant/src/pipeline/listing.py disney-pin-assistant/tests/test_listing.py
git commit -m "feat: add listing draft generation and comp-based pricing"
```

---

### Task 9: Pipeline Orchestrator

**Files:**
- Create: `disney-pin-assistant/src/pipeline/orchestrator.py`
- Create: `disney-pin-assistant/tests/test_routes_processing.py`
- Create: `disney-pin-assistant/src/routes/processing.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_routes_processing.py
import io
import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from src.main import app
from src.database import get_db
from src.models import Base, Pin, PinStatus

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession


@pytest.fixture
async def test_app_with_pins():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Seed with test pins
    async with session_factory() as session:
        for i in range(3):
            pin = Pin(
                batch_id="test-batch",
                status=PinStatus.UNPROCESSED,
                photo_type="front",
                image_paths=[f"/fake/pin{i}.jpg"],
            )
            session.add(pin)
        await session.commit()

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield app, session_factory
    app.dependency_overrides.clear()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_batch_progress(test_app_with_pins):
    test_app, _ = test_app_with_pins
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/batch/test-batch/progress")

    assert response.status_code == 200
    data = response.json()
    assert data["batch_id"] == "test-batch"
    assert data["total"] == 3
    assert data["processed"] == 0
    assert data["status_counts"]["unprocessed"] == 3
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd disney-pin-assistant
pytest tests/test_routes_processing.py -v
```

Expected: FAIL — route not found.

- [ ] **Step 3: Create src/pipeline/orchestrator.py**

```python
import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.config import settings
from src.models import (
    Pin, PinStatus, VisionExtraction, CatalogMatch,
    MatchStatus, Comp, ListingType, MatchType, ListingDraft, ExportStatus,
)
from src.pipeline.vision import extract_pin_metadata
from src.pipeline.matching import find_catalog_matches
from src.pipeline.comps import search_comps, filter_comps
from src.pipeline.listing import generate_listing_draft, compute_pricing


async def process_single_pin(session_factory: async_sessionmaker, pin_id: int) -> None:
    async with session_factory() as db:
        pin = await db.get(Pin, pin_id)
        if not pin or pin.status != PinStatus.UNPROCESSED:
            return

        # Step 1: Vision extraction
        extraction_data = await extract_pin_metadata(pin.image_paths)

        extraction = VisionExtraction(
            pin_id=pin.id,
            characters=extraction_data.get("characters", []),
            franchise=extraction_data.get("franchise"),
            collection_or_series=extraction_data.get("collection_or_series"),
            text_on_pin=extraction_data.get("text_on_pin"),
            visible_dates=extraction_data.get("visible_dates"),
            event_clues=extraction_data.get("event_clues"),
            pin_type=extraction_data.get("pin_type"),
            edition_size=extraction_data.get("edition_size"),
            condition_observations=extraction_data.get("condition_observations"),
            suggested_search_terms=extraction_data.get("suggested_search_terms", []),
            confidence_score=extraction_data.get("confidence_score", 0.0),
            raw_api_response=extraction_data,
        )
        db.add(extraction)
        pin.status = PinStatus.EXTRACTED
        await db.commit()

    # Step 2: Catalog matching
    async with session_factory() as db:
        pin = await db.get(Pin, pin_id)
        matches = await find_catalog_matches(db, extraction_data, max_results=3)

        for rank, match in enumerate(matches, 1):
            catalog_match = CatalogMatch(
                pin_id=pin.id,
                catalog_entry_id=match["catalog_entry_id"],
                match_confidence=match["confidence"],
                match_reasoning=match["reasoning"],
                rank=rank,
                status=MatchStatus.SUGGESTED,
            )
            db.add(catalog_match)

        if matches:
            pin.status = PinStatus.MATCHED
        await db.commit()

    # Step 3: Comp search
    async with session_factory() as db:
        pin = await db.get(Pin, pin_id)
        search_terms = extraction_data.get("suggested_search_terms", [])
        if matches:
            search_terms = [matches[0]["canonical_name"]] + search_terms

        sold_comps = await search_comps(search_terms[:1], listing_type="sold")
        active_comps = await search_comps(search_terms[:1], listing_type="active")
        all_comps = filter_comps(sold_comps + active_comps)

        for comp_data in all_comps:
            comp = Comp(
                pin_id=pin.id,
                ebay_listing_id=comp_data.get("ebay_listing_id"),
                title=comp_data["title"],
                price=comp_data["price"],
                sale_date=comp_data.get("sale_date"),
                listing_type=ListingType(comp_data["listing_type"]),
                condition=comp_data.get("condition"),
                match_type=MatchType.EXACT if matches else MatchType.NEAR,
                excluded=comp_data.get("excluded", False),
                exclusion_reason=comp_data.get("exclusion_reason"),
                raw_data=comp_data.get("raw_data"),
            )
            db.add(comp)

        pin.status = PinStatus.PRICED
        await db.commit()

    # Step 4: Listing generation
    async with session_factory() as db:
        pin = await db.get(Pin, pin_id)
        best_match = matches[0] if matches else None
        pricing = compute_pricing([
            {"price": c["price"], "listing_type": c["listing_type"], "excluded": c.get("excluded", False), "match_type": c.get("match_type", "near")}
            for c in all_comps
        ])

        draft_data = generate_listing_draft(extraction_data, best_match, pricing)

        draft = ListingDraft(
            pin_id=pin.id,
            title=draft_data["title"],
            description=draft_data["description"],
            item_specifics=draft_data["item_specifics"],
            suggested_price=draft_data["suggested_price"],
            quick_sale_price=draft_data["quick_sale_price"],
            price_confidence=draft_data["price_confidence"],
            pricing_reasoning=draft_data.get("pricing_reasoning"),
            tags_keywords=draft_data["tags_keywords"],
            export_status=ExportStatus.DRAFT,
        )
        db.add(draft)
        await db.commit()


async def process_batch(session_factory: async_sessionmaker, batch_id: str) -> None:
    async with session_factory() as db:
        result = await db.execute(
            select(Pin).where(Pin.batch_id == batch_id, Pin.status == PinStatus.UNPROCESSED)
        )
        pins = result.scalars().all()
        pin_ids = [p.id for p in pins]

    semaphore = asyncio.Semaphore(settings.max_concurrent_processing)

    async def limited_process(pid: int):
        async with semaphore:
            await process_single_pin(session_factory, pid)

    await asyncio.gather(*(limited_process(pid) for pid in pin_ids), return_exceptions=True)
```

- [ ] **Step 4: Create src/routes/processing.py**

```python
import asyncio

from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db, async_session
from src.models import Pin, PinStatus
from src.pipeline.orchestrator import process_batch

router = APIRouter(prefix="/api")


@router.post("/batch/{batch_id}/process")
async def start_batch_processing(
    batch_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(func.count(Pin.id)).where(Pin.batch_id == batch_id)
    )
    total = result.scalar()

    if total == 0:
        return {"error": "No pins found for batch"}

    # Import the session factory for background processing
    from src.database import async_session as session_factory
    background_tasks.add_task(process_batch, session_factory, batch_id)

    return {"batch_id": batch_id, "total": total, "status": "processing"}


@router.get("/batch/{batch_id}/progress")
async def batch_progress(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Pin.status, func.count(Pin.id))
        .where(Pin.batch_id == batch_id)
        .group_by(Pin.status)
    )
    rows = result.all()

    status_counts = {status.value: count for status, count in rows}
    total = sum(status_counts.values())
    processed = total - status_counts.get("unprocessed", 0)

    return {
        "batch_id": batch_id,
        "total": total,
        "processed": processed,
        "status_counts": status_counts,
    }
```

- [ ] **Step 5: Mount the processing router in main.py**

Add to `src/main.py`:

```python
from src.routes.processing import router as processing_router

# Add after existing router include:
app.include_router(processing_router)
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd disney-pin-assistant
pytest tests/test_routes_processing.py -v
```

Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
git add disney-pin-assistant/src/pipeline/orchestrator.py disney-pin-assistant/src/routes/processing.py disney-pin-assistant/src/main.py disney-pin-assistant/tests/test_routes_processing.py
git commit -m "feat: add batch processing orchestrator with concurrency control"
```

---

### Task 10: Pin CRUD and Review Actions

**Files:**
- Create: `disney-pin-assistant/src/routes/pins.py`
- Create: `disney-pin-assistant/tests/test_routes_pins.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_routes_pins.py
import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app
from src.database import get_db
from src.models import (
    Base, Pin, PinStatus, VisionExtraction, ListingDraft, ExportStatus,
)

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession


@pytest.fixture
async def test_app_with_data():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        pin = Pin(
            batch_id="test-batch",
            status=PinStatus.PRICED,
            photo_type="front",
            image_paths=["/fake/pin1.jpg"],
        )
        session.add(pin)
        await session.flush()

        extraction = VisionExtraction(
            pin_id=pin.id,
            characters=["Mickey Mouse"],
            franchise="Mickey & Friends",
            pin_type="limited edition",
            confidence_score=0.85,
            suggested_search_terms=["mickey mouse pin"],
        )
        session.add(extraction)

        draft = ListingDraft(
            pin_id=pin.id,
            title="Disney Mickey Mouse Pin LE",
            description="Test description",
            suggested_price=25.00,
            quick_sale_price=20.00,
            price_confidence="medium",
            tags_keywords=["mickey mouse", "disney pin"],
            export_status=ExportStatus.DRAFT,
        )
        session.add(draft)
        await session.commit()

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield app
    app.dependency_overrides.clear()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_list_batch_pins(test_app_with_data):
    transport = ASGITransport(app=test_app_with_data)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/batch/test-batch/pins")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["status"] == "priced"


@pytest.mark.asyncio
async def test_approve_pin(test_app_with_data):
    transport = ASGITransport(app=test_app_with_data)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/pins/1/approve")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "approved"


@pytest.mark.asyncio
async def test_update_pin_draft(test_app_with_data):
    transport = ASGITransport(app=test_app_with_data)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.patch(
            "/api/pins/1",
            json={"title": "Updated Title", "suggested_price": 30.00},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["listing_draft"]["title"] == "Updated Title"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd disney-pin-assistant
pytest tests/test_routes_pins.py -v
```

Expected: FAIL — route not found.

- [ ] **Step 3: Create src/routes/pins.py**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database import get_db
from src.models import Pin, PinStatus, ListingDraft, ExportStatus
from src.schemas import PinUpdateRequest

router = APIRouter(prefix="/api")


@router.get("/batch/{batch_id}/pins")
async def list_batch_pins(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Pin)
        .options(
            selectinload(Pin.extraction),
            selectinload(Pin.listing_draft),
            selectinload(Pin.catalog_matches),
            selectinload(Pin.comps),
        )
        .where(Pin.batch_id == batch_id)
    )
    pins = result.scalars().all()

    return [_pin_to_dict(pin) for pin in pins]


@router.get("/pins/{pin_id}")
async def get_pin_detail(
    pin_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Pin)
        .options(
            selectinload(Pin.extraction),
            selectinload(Pin.listing_draft),
            selectinload(Pin.catalog_matches),
            selectinload(Pin.comps),
        )
        .where(Pin.id == pin_id)
    )
    pin = result.scalar_one_or_none()
    if not pin:
        raise HTTPException(status_code=404, detail="Pin not found")

    return _pin_to_dict(pin)


@router.post("/pins/{pin_id}/approve")
async def approve_pin(
    pin_id: int,
    db: AsyncSession = Depends(get_db),
):
    pin = await db.get(Pin, pin_id)
    if not pin:
        raise HTTPException(status_code=404, detail="Pin not found")

    pin.status = PinStatus.APPROVED

    result = await db.execute(
        select(ListingDraft).where(ListingDraft.pin_id == pin_id)
    )
    draft = result.scalar_one_or_none()
    if draft:
        draft.export_status = ExportStatus.APPROVED

    await db.commit()
    return {"id": pin.id, "status": pin.status.value}


@router.post("/pins/{pin_id}/skip")
async def skip_pin(
    pin_id: int,
    db: AsyncSession = Depends(get_db),
):
    pin = await db.get(Pin, pin_id)
    if not pin:
        raise HTTPException(status_code=404, detail="Pin not found")

    pin.seller_notes = (pin.seller_notes or "") + " [SKIPPED]"
    await db.commit()
    return {"id": pin.id, "status": pin.status.value, "skipped": True}


@router.patch("/pins/{pin_id}")
async def update_pin(
    pin_id: int,
    update: PinUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Pin)
        .options(
            selectinload(Pin.extraction),
            selectinload(Pin.listing_draft),
            selectinload(Pin.catalog_matches),
            selectinload(Pin.comps),
        )
        .where(Pin.id == pin_id)
    )
    pin = result.scalar_one_or_none()
    if not pin:
        raise HTTPException(status_code=404, detail="Pin not found")

    if pin.listing_draft:
        edits = pin.listing_draft.seller_edits or {}
        if update.title is not None:
            edits["title"] = {"old": pin.listing_draft.title, "new": update.title}
            pin.listing_draft.title = update.title
        if update.description is not None:
            edits["description"] = {"old": pin.listing_draft.description, "new": update.description}
            pin.listing_draft.description = update.description
        if update.suggested_price is not None:
            edits["suggested_price"] = {"old": pin.listing_draft.suggested_price, "new": update.suggested_price}
            pin.listing_draft.suggested_price = update.suggested_price
        if update.tags_keywords is not None:
            pin.listing_draft.tags_keywords = update.tags_keywords
        pin.listing_draft.seller_edits = edits

    if update.seller_notes is not None:
        pin.seller_notes = update.seller_notes

    await db.commit()
    return _pin_to_dict(pin)


def _pin_to_dict(pin: Pin) -> dict:
    data = {
        "id": pin.id,
        "batch_id": pin.batch_id,
        "status": pin.status.value,
        "photo_type": pin.photo_type,
        "seller_notes": pin.seller_notes,
        "image_paths": pin.image_paths,
        "extraction": None,
        "catalog_matches": [],
        "comps": [],
        "listing_draft": None,
    }

    if pin.extraction:
        data["extraction"] = {
            "characters": pin.extraction.characters,
            "franchise": pin.extraction.franchise,
            "pin_type": pin.extraction.pin_type,
            "confidence_score": pin.extraction.confidence_score,
            "suggested_search_terms": pin.extraction.suggested_search_terms,
        }

    if pin.listing_draft:
        data["listing_draft"] = {
            "title": pin.listing_draft.title,
            "description": pin.listing_draft.description,
            "suggested_price": pin.listing_draft.suggested_price,
            "quick_sale_price": pin.listing_draft.quick_sale_price,
            "price_confidence": pin.listing_draft.price_confidence,
            "tags_keywords": pin.listing_draft.tags_keywords,
            "export_status": pin.listing_draft.export_status.value,
        }

    for comp in pin.comps:
        data["comps"].append({
            "title": comp.title,
            "price": comp.price,
            "listing_type": comp.listing_type.value,
            "excluded": comp.excluded,
        })

    return data
```

- [ ] **Step 4: Mount the pins router in main.py**

Add to `src/main.py`:

```python
from src.routes.pins import router as pins_router

# Add after existing router includes:
app.include_router(pins_router)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd disney-pin-assistant
pytest tests/test_routes_pins.py -v
```

Expected: All 3 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add disney-pin-assistant/src/routes/pins.py disney-pin-assistant/src/main.py disney-pin-assistant/tests/test_routes_pins.py
git commit -m "feat: add pin CRUD, approve, skip, and update endpoints"
```

---

### Task 11: CSV Export

**Files:**
- Create: `disney-pin-assistant/src/routes/export.py`
- Create: `disney-pin-assistant/tests/test_routes_export.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_routes_export.py
import csv
import io
import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app
from src.database import get_db
from src.models import (
    Base, Pin, PinStatus, ListingDraft, ExportStatus,
)

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession


@pytest.fixture
async def test_app_with_approved():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        pin = Pin(
            batch_id="export-batch",
            status=PinStatus.APPROVED,
            image_paths=["/fake/pin1.jpg"],
        )
        session.add(pin)
        await session.flush()

        draft = ListingDraft(
            pin_id=pin.id,
            title="Disney Mickey Mouse Pin LE/3000",
            description="Limited edition Mickey Mouse pin",
            item_specifics={"Brand": "Disney", "Character": "Mickey Mouse"},
            suggested_price=25.00,
            quick_sale_price=20.00,
            price_confidence="medium",
            tags_keywords=["mickey mouse", "disney pin"],
            export_status=ExportStatus.APPROVED,
        )
        session.add(draft)
        await session.commit()

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield app
    app.dependency_overrides.clear()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_export_csv(test_app_with_approved):
    transport = ASGITransport(app=test_app_with_approved)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/batch/export-batch/export")

    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]

    reader = csv.DictReader(io.StringIO(response.text))
    rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["Title"] == "Disney Mickey Mouse Pin LE/3000"
    assert rows[0]["Price"] == "25.0"


@pytest.mark.asyncio
async def test_export_empty_batch(test_app_with_approved):
    transport = ASGITransport(app=test_app_with_approved)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/batch/nonexistent/export")

    assert response.status_code == 200
    reader = csv.DictReader(io.StringIO(response.text))
    rows = list(reader)
    assert len(rows) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd disney-pin-assistant
pytest tests/test_routes_export.py -v
```

Expected: FAIL — route not found.

- [ ] **Step 3: Create src/routes/export.py**

```python
import csv
import io

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database import get_db
from src.models import Pin, PinStatus, ListingDraft, ExportStatus

router = APIRouter(prefix="/api")

CSV_COLUMNS = [
    "Title", "Description", "Price", "Quick Sale Price",
    "Price Confidence", "Category", "Tags",
    "Brand", "Character", "Franchise", "Type", "Edition Size", "Year",
]


@router.get("/batch/{batch_id}/export")
async def export_batch_csv(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Pin)
        .options(selectinload(Pin.listing_draft))
        .where(
            Pin.batch_id == batch_id,
            Pin.status == PinStatus.APPROVED,
        )
    )
    pins = result.scalars().all()

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS)
    writer.writeheader()

    for pin in pins:
        draft = pin.listing_draft
        if not draft:
            continue

        specifics = draft.item_specifics or {}
        writer.writerow({
            "Title": draft.title,
            "Description": draft.description or "",
            "Price": draft.suggested_price,
            "Quick Sale Price": draft.quick_sale_price,
            "Price Confidence": draft.price_confidence,
            "Category": draft.category_suggestion or "",
            "Tags": ", ".join(draft.tags_keywords or []),
            "Brand": specifics.get("Brand", ""),
            "Character": specifics.get("Character", ""),
            "Franchise": specifics.get("Franchise", ""),
            "Type": specifics.get("Type", ""),
            "Edition Size": specifics.get("Edition Size", ""),
            "Year": specifics.get("Year", ""),
        })

    # Mark as exported
    for pin in pins:
        if pin.listing_draft:
            pin.listing_draft.export_status = ExportStatus.EXPORTED
        pin.status = PinStatus.EXPORTED
    await db.commit()

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={batch_id}-listings.csv"},
    )
```

- [ ] **Step 4: Mount the export router in main.py**

Add to `src/main.py`:

```python
from src.routes.export import router as export_router

# Add after existing router includes:
app.include_router(export_router)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd disney-pin-assistant
pytest tests/test_routes_export.py -v
```

Expected: All 2 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add disney-pin-assistant/src/routes/export.py disney-pin-assistant/src/main.py disney-pin-assistant/tests/test_routes_export.py
git commit -m "feat: add CSV export for approved listing drafts"
```

---

### Task 12: Web UI — Base Layout and Upload Page

**Files:**
- Create: `disney-pin-assistant/src/templates/base.html`
- Create: `disney-pin-assistant/src/templates/upload.html`
- Create: `disney-pin-assistant/static/style.css`
- Create: `disney-pin-assistant/static/app.js`
- Create: `disney-pin-assistant/src/routes/pages.py`
- Modify: `disney-pin-assistant/src/main.py`

- [ ] **Step 1: Create src/templates/base.html**

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Disney Pin Assistant</title>
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
    <header>
        <h1><a href="/">Disney Pin Assistant</a></h1>
    </header>
    <main>
        {% block content %}{% endblock %}
    </main>
    <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create src/templates/upload.html**

```html
{% extends "base.html" %}
{% block content %}
<div class="upload-container">
    <h2>Upload Pin Photos</h2>
    <form id="upload-form" enctype="multipart/form-data">
        <div class="drop-zone" id="drop-zone">
            <p>Drag & drop photos here, or click to select</p>
            <input type="file" id="file-input" name="files" multiple accept="image/*" hidden>
        </div>
        <div id="file-list"></div>
        <div class="form-group">
            <label for="photo-type">Photo type:</label>
            <select id="photo-type" name="photo_type">
                <option value="">Unknown</option>
                <option value="front">Front</option>
                <option value="backstamp">Backstamp</option>
                <option value="group">Group (multiple pins)</option>
            </select>
        </div>
        <button type="submit" id="upload-btn" disabled>Upload & Process</button>
    </form>
    <div id="progress-container" hidden>
        <h3>Processing batch: <span id="batch-id"></span></h3>
        <div class="progress-bar">
            <div class="progress-fill" id="progress-fill"></div>
        </div>
        <p><span id="processed-count">0</span> / <span id="total-count">0</span> pins processed</p>
        <a id="review-link" href="#" hidden>Go to Review Queue →</a>
    </div>
</div>
{% endblock %}
```

- [ ] **Step 3: Create static/style.css**

```css
* { box-sizing: border-box; margin: 0; padding: 0; }

body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #f5f5f5;
    color: #333;
    line-height: 1.6;
}

header {
    background: #1a1a2e;
    color: white;
    padding: 1rem 2rem;
}

header a { color: white; text-decoration: none; }

main { max-width: 1200px; margin: 2rem auto; padding: 0 1rem; }

.upload-container { max-width: 600px; margin: 0 auto; }

.drop-zone {
    border: 2px dashed #ccc;
    border-radius: 8px;
    padding: 3rem;
    text-align: center;
    cursor: pointer;
    transition: border-color 0.2s;
    margin-bottom: 1rem;
}

.drop-zone:hover, .drop-zone.dragover { border-color: #4a90d9; background: #f0f7ff; }

.form-group { margin: 1rem 0; }

label { display: block; margin-bottom: 0.25rem; font-weight: 500; }

select, input { padding: 0.5rem; border: 1px solid #ccc; border-radius: 4px; }

button {
    background: #4a90d9;
    color: white;
    border: none;
    padding: 0.75rem 1.5rem;
    border-radius: 4px;
    cursor: pointer;
    font-size: 1rem;
}

button:disabled { background: #ccc; cursor: not-allowed; }

button:hover:not(:disabled) { background: #357abd; }

#file-list { margin: 0.5rem 0; font-size: 0.9rem; color: #666; }

.progress-bar {
    background: #e0e0e0;
    border-radius: 8px;
    height: 24px;
    overflow: hidden;
    margin: 1rem 0;
}

.progress-fill {
    background: #4a90d9;
    height: 100%;
    width: 0%;
    transition: width 0.3s;
}

/* Review queue styles */
.queue-table {
    width: 100%;
    border-collapse: collapse;
    background: white;
    border-radius: 8px;
    overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}

.queue-table th {
    background: #1a1a2e;
    color: white;
    padding: 0.75rem 1rem;
    text-align: left;
}

.queue-table td {
    padding: 0.75rem 1rem;
    border-bottom: 1px solid #eee;
    vertical-align: middle;
}

.queue-table tr:hover { background: #f8f8f8; }

.queue-table img { width: 60px; height: 60px; object-fit: cover; border-radius: 4px; }

.confidence-high { color: #27ae60; font-weight: bold; }
.confidence-medium { color: #f39c12; font-weight: bold; }
.confidence-low { color: #e74c3c; font-weight: bold; }

.status-badge {
    display: inline-block;
    padding: 0.25rem 0.5rem;
    border-radius: 12px;
    font-size: 0.8rem;
    font-weight: 500;
}

.status-unprocessed { background: #eee; }
.status-extracted { background: #d4efdf; }
.status-matched { background: #d5f5e3; }
.status-priced { background: #fdebd0; }
.status-approved { background: #d4efdf; color: #27ae60; }
.status-exported { background: #d5dbef; }

.actions { display: flex; gap: 0.5rem; }

.btn-approve { background: #27ae60; color: white; border: none; padding: 0.4rem 0.8rem; border-radius: 4px; cursor: pointer; }
.btn-skip { background: #95a5a6; color: white; border: none; padding: 0.4rem 0.8rem; border-radius: 4px; cursor: pointer; }
.btn-edit { background: #3498db; color: white; border: none; padding: 0.4rem 0.8rem; border-radius: 4px; cursor: pointer; }
.btn-export { background: #8e44ad; color: white; border: none; padding: 0.75rem 1.5rem; border-radius: 4px; cursor: pointer; font-size: 1rem; }

/* Detail view */
.detail-container { display: grid; grid-template-columns: 1fr 1fr; gap: 2rem; }

.detail-image img { max-width: 100%; border-radius: 8px; }

.detail-form label { display: block; margin-top: 1rem; font-weight: 500; }
.detail-form input, .detail-form textarea {
    width: 100%;
    padding: 0.5rem;
    border: 1px solid #ccc;
    border-radius: 4px;
    margin-top: 0.25rem;
}
.detail-form textarea { height: 100px; resize: vertical; }

.comp-list { list-style: none; margin-top: 1rem; }
.comp-list li {
    padding: 0.5rem;
    border-bottom: 1px solid #eee;
    display: flex;
    justify-content: space-between;
}
.comp-excluded { opacity: 0.5; text-decoration: line-through; }

.batch-actions { margin: 1rem 0; display: flex; gap: 1rem; align-items: center; }

.filter-bar { margin: 1rem 0; display: flex; gap: 1rem; align-items: center; }
.filter-bar select { padding: 0.4rem; }
```

- [ ] **Step 4: Create static/app.js**

```javascript
// Upload handling
const dropZone = document.getElementById("drop-zone");
const fileInput = document.getElementById("file-input");
const fileList = document.getElementById("file-list");
const uploadForm = document.getElementById("upload-form");
const uploadBtn = document.getElementById("upload-btn");

if (dropZone) {
    dropZone.addEventListener("click", () => fileInput.click());
    dropZone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropZone.classList.add("dragover");
    });
    dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
    dropZone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropZone.classList.remove("dragover");
        fileInput.files = e.dataTransfer.files;
        updateFileList();
    });

    fileInput.addEventListener("change", updateFileList);

    uploadForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const formData = new FormData();
        for (const file of fileInput.files) {
            formData.append("files", file);
        }
        const photoType = document.getElementById("photo-type").value;
        if (photoType) {
            formData.append("photo_type", photoType);
        }

        uploadBtn.disabled = true;
        uploadBtn.textContent = "Uploading...";

        const response = await fetch("/api/upload", { method: "POST", body: formData });
        const data = await response.json();

        // Start processing
        await fetch(`/api/batch/${data.batch_id}/process`, { method: "POST" });

        // Show progress
        document.getElementById("progress-container").hidden = false;
        document.getElementById("batch-id").textContent = data.batch_id;
        document.getElementById("total-count").textContent = data.pins.length;

        pollProgress(data.batch_id, data.pins.length);
    });
}

function updateFileList() {
    const files = fileInput.files;
    fileList.textContent = `${files.length} file(s) selected`;
    uploadBtn.disabled = files.length === 0;
}

async function pollProgress(batchId, total) {
    const interval = setInterval(async () => {
        const response = await fetch(`/api/batch/${batchId}/progress`);
        const data = await response.json();

        document.getElementById("processed-count").textContent = data.processed;
        const pct = Math.round((data.processed / total) * 100);
        document.getElementById("progress-fill").style.width = `${pct}%`;

        if (data.processed >= total) {
            clearInterval(interval);
            const link = document.getElementById("review-link");
            link.href = `/queue/${batchId}`;
            link.hidden = false;
        }
    }, 2000);
}

// Review queue actions
async function approvePin(pinId) {
    await fetch(`/api/pins/${pinId}/approve`, { method: "POST" });
    location.reload();
}

async function skipPin(pinId) {
    await fetch(`/api/pins/${pinId}/skip`, { method: "POST" });
    location.reload();
}

async function approveAllHighConfidence(batchId) {
    const response = await fetch(`/api/batch/${batchId}/pins`);
    const pins = await response.json();

    for (const pin of pins) {
        if (pin.extraction && pin.extraction.confidence_score >= 0.8 && pin.status === "priced") {
            await fetch(`/api/pins/${pin.id}/approve`, { method: "POST" });
        }
    }
    location.reload();
}

// Detail view save
async function savePin(pinId) {
    const title = document.getElementById("edit-title").value;
    const description = document.getElementById("edit-description").value;
    const price = parseFloat(document.getElementById("edit-price").value);

    await fetch(`/api/pins/${pinId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, description, suggested_price: price }),
    });

    alert("Saved!");
}
```

- [ ] **Step 5: Create src/routes/pages.py**

```python
from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="src/templates")


@router.get("/")
async def upload_page(request: Request):
    return templates.TemplateResponse("upload.html", {"request": request})
```

- [ ] **Step 6: Mount the pages router in main.py**

Add to `src/main.py`:

```python
from src.routes.pages import router as pages_router

# Add after existing router includes:
app.include_router(pages_router)
```

- [ ] **Step 7: Verify the app starts and upload page loads**

```bash
cd disney-pin-assistant
uvicorn src.main:app --reload --port 8000
```

Visit `http://localhost:8000/` — upload page should render with drag-and-drop zone.

- [ ] **Step 8: Commit**

```bash
git add disney-pin-assistant/src/templates/ disney-pin-assistant/static/ disney-pin-assistant/src/routes/pages.py disney-pin-assistant/src/main.py
git commit -m "feat: add web UI base layout, upload page, and styles"
```

---

### Task 13: Web UI — Review Queue and Detail Pages

**Files:**
- Create: `disney-pin-assistant/src/templates/queue.html`
- Create: `disney-pin-assistant/src/templates/detail.html`
- Modify: `disney-pin-assistant/src/routes/pages.py`

- [ ] **Step 1: Create src/templates/queue.html**

```html
{% extends "base.html" %}
{% block content %}
<h2>Review Queue — Batch {{ batch_id }}</h2>

<div class="batch-actions">
    <button class="btn-approve" onclick="approveAllHighConfidence('{{ batch_id }}')">Approve All High Confidence</button>
    <a href="/api/batch/{{ batch_id }}/export" class="btn-export">Export Approved as CSV</a>
</div>

<div class="filter-bar">
    <label>Filter by status:</label>
    <select id="status-filter" onchange="filterTable()">
        <option value="">All</option>
        <option value="extracted">Extracted</option>
        <option value="matched">Matched</option>
        <option value="priced">Priced</option>
        <option value="approved">Approved</option>
    </select>
</div>

<table class="queue-table">
    <thead>
        <tr>
            <th>Image</th>
            <th>Title</th>
            <th>Confidence</th>
            <th>Price</th>
            <th>Status</th>
            <th>Actions</th>
        </tr>
    </thead>
    <tbody id="pins-table-body">
    </tbody>
</table>

<script>
async function loadPins() {
    const response = await fetch(`/api/batch/{{ batch_id }}/pins`);
    const pins = await response.json();
    const tbody = document.getElementById("pins-table-body");
    tbody.innerHTML = "";

    for (const pin of pins) {
        const draft = pin.listing_draft;
        const extraction = pin.extraction;
        const title = draft ? draft.title : "(not yet processed)";
        const confidence = extraction ? extraction.confidence_score : 0;
        const price = draft ? `$${draft.suggested_price || "—"}` : "—";

        let confClass = "confidence-low";
        if (confidence >= 0.8) confClass = "confidence-high";
        else if (confidence >= 0.5) confClass = "confidence-medium";

        const imgSrc = pin.image_paths.length > 0 ? `/uploads/${pin.image_paths[0].split("/").pop()}` : "";

        const row = document.createElement("tr");
        row.dataset.status = pin.status;
        row.innerHTML = `
            <td><img src="${imgSrc}" alt="pin" onerror="this.style.display='none'"></td>
            <td><a href="/pins/${pin.id}">${title}</a></td>
            <td class="${confClass}">${(confidence * 100).toFixed(0)}%</td>
            <td>${price}</td>
            <td><span class="status-badge status-${pin.status}">${pin.status}</span></td>
            <td class="actions">
                ${pin.status !== "approved" && pin.status !== "exported" ? `
                    <button class="btn-approve" onclick="approvePin(${pin.id})">Approve</button>
                    <button class="btn-skip" onclick="skipPin(${pin.id})">Skip</button>
                ` : ""}
                <a href="/pins/${pin.id}" class="btn-edit">Detail</a>
            </td>
        `;
        tbody.appendChild(row);
    }
}

function filterTable() {
    const filter = document.getElementById("status-filter").value;
    const rows = document.querySelectorAll("#pins-table-body tr");
    for (const row of rows) {
        row.style.display = (!filter || row.dataset.status === filter) ? "" : "none";
    }
}

loadPins();
</script>
{% endblock %}
```

- [ ] **Step 2: Create src/templates/detail.html**

```html
{% extends "base.html" %}
{% block content %}
<div id="pin-detail">
    <a href="/queue/{{ batch_id }}">← Back to Queue</a>
    <h2>Pin #{{ pin_id }}</h2>
    <div class="detail-container" id="detail-content">
        Loading...
    </div>
</div>

<script>
async function loadDetail() {
    const response = await fetch(`/api/pins/{{ pin_id }}`);
    const pin = await response.json();
    const container = document.getElementById("detail-content");

    const draft = pin.listing_draft;
    const extraction = pin.extraction;
    const imgSrc = pin.image_paths.length > 0 ? `/uploads/${pin.image_paths[0].split("/").pop()}` : "";

    let compsHtml = "<h3>Comps</h3><ul class='comp-list'>";
    for (const comp of pin.comps) {
        const cls = comp.excluded ? "comp-excluded" : "";
        compsHtml += `<li class="${cls}"><span>${comp.title}</span><span>$${comp.price.toFixed(2)} (${comp.listing_type})</span></li>`;
    }
    compsHtml += "</ul>";

    let extractionHtml = "";
    if (extraction) {
        extractionHtml = `
            <h3>Vision Extraction</h3>
            <p><strong>Characters:</strong> ${(extraction.characters || []).join(", ")}</p>
            <p><strong>Franchise:</strong> ${extraction.franchise || "—"}</p>
            <p><strong>Pin Type:</strong> ${extraction.pin_type || "—"}</p>
            <p><strong>Confidence:</strong> ${(extraction.confidence_score * 100).toFixed(0)}%</p>
        `;
    }

    container.innerHTML = `
        <div class="detail-image">
            <img src="${imgSrc}" alt="pin photo" onerror="this.alt='No image'">
            ${extractionHtml}
            ${compsHtml}
        </div>
        <div class="detail-form">
            <h3>Listing Draft</h3>
            <label>Title</label>
            <input type="text" id="edit-title" value="${draft ? draft.title : ""}" maxlength="80">
            <label>Description</label>
            <textarea id="edit-description">${draft ? draft.description : ""}</textarea>
            <label>Price</label>
            <input type="number" id="edit-price" value="${draft ? draft.suggested_price : ""}" step="0.01">
            <p style="margin-top:0.5rem;color:#666">
                Quick sale: $${draft ? draft.quick_sale_price : "—"} |
                Confidence: ${draft ? draft.price_confidence : "—"}
            </p>
            <label>Tags</label>
            <input type="text" id="edit-tags" value="${draft ? draft.tags_keywords.join(", ") : ""}">
            <div style="margin-top:1.5rem;display:flex;gap:1rem;">
                <button class="btn-approve" onclick="saveAndApprove(${pin.id})">Save & Approve</button>
                <button class="btn-edit" onclick="savePin(${pin.id})">Save Draft</button>
                <button class="btn-skip" onclick="skipPin(${pin.id})">Skip</button>
            </div>
        </div>
    `;
}

async function saveAndApprove(pinId) {
    await savePin(pinId);
    await fetch(`/api/pins/${pinId}/approve`, { method: "POST" });
    window.location.href = document.querySelector("a").href;
}

loadDetail();
</script>
{% endblock %}
```

- [ ] **Step 3: Add queue and detail page routes**

Add to `src/routes/pages.py`:

```python
@router.get("/queue/{batch_id}")
async def queue_page(request: Request, batch_id: str):
    return templates.TemplateResponse("queue.html", {"request": request, "batch_id": batch_id})


@router.get("/pins/{pin_id}")
async def detail_page(request: Request, pin_id: int):
    # Get batch_id for back link
    return templates.TemplateResponse("detail.html", {"request": request, "pin_id": pin_id, "batch_id": ""})
```

- [ ] **Step 4: Add static file serving for uploads directory**

Add to `src/main.py`:

```python
from pathlib import Path
from src.config import settings

# Add after existing static mount:
settings.upload_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(settings.upload_dir)), name="uploads")
```

- [ ] **Step 5: Verify the full UI works**

```bash
cd disney-pin-assistant
uvicorn src.main:app --reload --port 8000
```

Visit:
- `http://localhost:8000/` — upload page
- `http://localhost:8000/queue/test-batch` — review queue (empty)

- [ ] **Step 6: Commit**

```bash
git add disney-pin-assistant/src/templates/ disney-pin-assistant/src/routes/pages.py disney-pin-assistant/src/main.py
git commit -m "feat: add review queue and pin detail web UI pages"
```

---

### Task 14: Catalog Management Endpoint

**Files:**
- Create: `disney-pin-assistant/src/routes/catalog.py`
- Modify: `disney-pin-assistant/src/main.py`

- [ ] **Step 1: Create src/routes/catalog.py**

```python
import csv
import io
import json

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models import CatalogEntry

router = APIRouter(prefix="/api/catalog")


@router.get("/stats")
async def catalog_stats(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(func.count(CatalogEntry.id)))
    total = result.scalar()
    return {"total_entries": total}


@router.post("/import/csv")
async def import_catalog_csv(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()
    reader = csv.DictReader(io.StringIO(content.decode("utf-8")))

    count = 0
    for row in reader:
        entry = CatalogEntry(
            canonical_name=row.get("name", ""),
            characters=json.loads(row.get("characters", "[]")),
            franchise=row.get("franchise"),
            series_or_collection=row.get("series"),
            event=row.get("event"),
            edition_size=int(row["edition_size"]) if row.get("edition_size") else None,
            release_year=int(row["release_year"]) if row.get("release_year") else None,
            pin_type=row.get("pin_type"),
            exclusive_source=row.get("exclusive_source"),
            source=row.get("source", "manual"),
            source_reference_id=row.get("reference_id"),
            reference_image_url=row.get("image_url"),
            evidence_strength=row.get("evidence_strength", "medium"),
        )
        db.add(entry)
        count += 1

    await db.commit()
    return {"imported": count}


@router.post("/import/json")
async def import_catalog_json(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()
    entries = json.loads(content.decode("utf-8"))

    if not isinstance(entries, list):
        raise HTTPException(status_code=400, detail="Expected a JSON array")

    count = 0
    for item in entries:
        entry = CatalogEntry(
            canonical_name=item.get("canonical_name", item.get("name", "")),
            alternate_names=item.get("alternate_names", []),
            characters=item.get("characters", []),
            franchise=item.get("franchise"),
            series_or_collection=item.get("series_or_collection"),
            event=item.get("event"),
            edition_size=item.get("edition_size"),
            release_year=item.get("release_year"),
            pin_type=item.get("pin_type"),
            exclusive_source=item.get("exclusive_source"),
            source=item.get("source", "import"),
            source_reference_id=item.get("source_reference_id"),
            reference_image_url=item.get("reference_image_url"),
            evidence_strength=item.get("evidence_strength", "medium"),
        )
        db.add(entry)
        count += 1

    await db.commit()
    return {"imported": count}


@router.get("/search")
async def search_catalog(
    q: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(CatalogEntry).where(
            CatalogEntry.canonical_name.ilike(f"%{q}%")
        ).limit(20)
    )
    entries = result.scalars().all()

    return [
        {
            "id": e.id,
            "canonical_name": e.canonical_name,
            "characters": e.characters,
            "franchise": e.franchise,
            "event": e.event,
            "edition_size": e.edition_size,
            "pin_type": e.pin_type,
            "evidence_strength": e.evidence_strength,
        }
        for e in entries
    ]
```

- [ ] **Step 2: Mount the catalog router in main.py**

Add to `src/main.py`:

```python
from src.routes.catalog import router as catalog_router

# Add after existing router includes:
app.include_router(catalog_router)
```

- [ ] **Step 3: Verify catalog endpoints work**

```bash
cd disney-pin-assistant
uvicorn src.main:app --reload --port 8000
```

Visit `http://localhost:8000/api/catalog/stats` — expected: `{"total_entries": 0}`

- [ ] **Step 4: Commit**

```bash
git add disney-pin-assistant/src/routes/catalog.py disney-pin-assistant/src/main.py
git commit -m "feat: add catalog management endpoints for CSV/JSON import and search"
```

---

### Task 15: Integration Test — Full Pipeline

**Files:**
- Create: `disney-pin-assistant/tests/test_integration.py`

- [ ] **Step 1: Write the integration test**

```python
# tests/test_integration.py
import io
import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from src.main import app
from src.database import get_db
from src.models import Base, Pin, PinStatus, CatalogEntry

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession


@pytest.fixture
async def full_test_app():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Seed catalog
    async with session_factory() as session:
        entry = CatalogEntry(
            canonical_name="Mickey Mouse Epcot Food & Wine 2019 LE 3000",
            characters=["Mickey Mouse"],
            franchise="Mickey & Friends",
            event="Epcot Food & Wine Festival",
            edition_size=3000,
            release_year=2019,
            pin_type="limited edition",
            source="test",
            evidence_strength="high",
        )
        session.add(entry)
        await session.commit()

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield app, session_factory
    app.dependency_overrides.clear()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_full_pipeline(full_test_app):
    test_app, session_factory = full_test_app

    mock_vision = {
        "characters": ["Mickey Mouse"],
        "franchise": "Mickey & Friends",
        "collection_or_series": None,
        "text_on_pin": "Epcot",
        "visible_dates": "2019",
        "event_clues": "Food & Wine Festival",
        "pin_type": "limited edition",
        "edition_size": 3000,
        "condition_observations": "Excellent",
        "suggested_search_terms": ["mickey mouse food wine 2019 le pin"],
        "confidence_score": 0.9,
    }

    mock_comps = [
        {
            "itemId": "111",
            "title": "Mickey Food Wine 2019 Pin LE 3000",
            "price": {"value": "24.99", "currency": "USD"},
            "condition": "New",
            "itemEndDate": "2026-03-15",
        },
    ]

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Step 1: Upload
        response = await client.post(
            "/api/upload",
            files=[("files", ("pin.jpg", io.BytesIO(b"fake"), "image/jpeg"))],
            data={"photo_type": "front"},
        )
        assert response.status_code == 200
        batch_id = response.json()["batch_id"]

        # Step 2: Process (with mocked external calls)
        with patch("src.pipeline.vision.call_vision_api", new_callable=AsyncMock, return_value=mock_vision), \
             patch("src.pipeline.comps.ebay_search", new_callable=AsyncMock, return_value=mock_comps):

            from src.pipeline.orchestrator import process_batch
            await process_batch(session_factory, batch_id)

        # Step 3: Check results
        response = await client.get(f"/api/batch/{batch_id}/pins")
        assert response.status_code == 200
        pins = response.json()
        assert len(pins) == 1

        pin = pins[0]
        assert pin["extraction"] is not None
        assert pin["extraction"]["characters"] == ["Mickey Mouse"]
        assert pin["listing_draft"] is not None
        assert "Mickey Mouse" in pin["listing_draft"]["title"]
        assert pin["listing_draft"]["suggested_price"] is not None

        # Step 4: Approve
        response = await client.post(f"/api/pins/{pin['id']}/approve")
        assert response.status_code == 200
        assert response.json()["status"] == "approved"

        # Step 5: Export
        response = await client.get(f"/api/batch/{batch_id}/export")
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        assert "Mickey Mouse" in response.text
```

- [ ] **Step 2: Run the integration test**

```bash
cd disney-pin-assistant
pytest tests/test_integration.py -v
```

Expected: PASS — full pipeline from upload to export works end-to-end.

- [ ] **Step 3: Run all tests**

```bash
cd disney-pin-assistant
pytest tests/ -v
```

Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add disney-pin-assistant/tests/test_integration.py
git commit -m "test: add full pipeline integration test (upload → process → approve → export)"
```

---

### Task 16: Discovery — Catalog Source Evaluation

**Files:**
- Create: `disney-pin-assistant/docs/catalog-source-evaluation.md`

This is a research task, not a code task. The engineer should:

- [ ] **Step 1: Research community pin databases**

Investigate these sources for Disney pin catalog data:
- PinPics (pinpics.com) — the largest community database
- Disney Pin Trading Database
- PinCollector.com
- Reddit r/DisneyPinSwap community resources

For each source, document:
- Accessibility (is there an API? Is it scrapeable? Are there data exports?)
- Data quality (how complete are entries? What fields are available?)
- Coverage (roughly how many pins are cataloged?)
- Legal/TOS considerations

- [ ] **Step 2: Document findings**

Write findings to `disney-pin-assistant/docs/catalog-source-evaluation.md` with:
- Source name and URL
- Data availability assessment
- Recommended approach for each source
- Overall recommendation for initial catalog seeding strategy

- [ ] **Step 3: Commit**

```bash
git add disney-pin-assistant/docs/catalog-source-evaluation.md
git commit -m "docs: add catalog source evaluation for initial seeding strategy"
```

---

### Task 17: Discovery — Vision Prompt Quality Testing

**Files:**
- Create: `disney-pin-assistant/scripts/test_vision_quality.py`

- [ ] **Step 1: Create the test script**

```python
# scripts/test_vision_quality.py
"""
Manual vision quality test script.
Place sample pin photos in sample_data/ directory, then run:
    python scripts/test_vision_quality.py

Outputs structured results for each image to stdout.
"""
import asyncio
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pipeline.vision import extract_pin_metadata


async def main():
    sample_dir = Path("sample_data")
    if not sample_dir.exists():
        print("Create a sample_data/ directory with pin photos first.")
        return

    image_files = sorted(
        p for p in sample_dir.iterdir()
        if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )

    if not image_files:
        print("No image files found in sample_data/")
        return

    print(f"Testing {len(image_files)} images...\n")

    results = []
    for img_path in image_files:
        print(f"Processing: {img_path.name}")
        try:
            result = await extract_pin_metadata([str(img_path)])
            result["_file"] = img_path.name
            results.append(result)

            print(f"  Characters: {result.get('characters', [])}")
            print(f"  Franchise: {result.get('franchise')}")
            print(f"  Pin Type: {result.get('pin_type')}")
            print(f"  Edition: {result.get('edition_size')}")
            print(f"  Confidence: {result.get('confidence_score')}")
            print(f"  Search Terms: {result.get('suggested_search_terms', [])}")
            print()
        except Exception as e:
            print(f"  ERROR: {e}\n")
            results.append({"_file": img_path.name, "_error": str(e)})

    output_path = Path("sample_data/vision_results.json")
    output_path.write_text(json.dumps(results, indent=2))
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Gather 10-20 sample pin photos**

Place sample Disney pin photos in `sample_data/` directory. Include a mix of:
- Common rack pins
- Limited edition pins
- Mystery pins
- Event/festival pins
- Pins with clear backstamp text

- [ ] **Step 3: Run the quality test**

```bash
cd disney-pin-assistant
python scripts/test_vision_quality.py
```

Review the output. For each pin, manually grade:
- Character identification: correct / partially correct / wrong
- Pin type: correct / wrong
- Edition info: detected / missed / N/A
- Search terms: useful / not useful

- [ ] **Step 4: Tune the vision prompt based on results**

If patterns emerge (e.g., consistently missing backstamp text, misclassifying pin types), update `VISION_PROMPT` in `src/pipeline/vision.py` to address them.

- [ ] **Step 5: Commit**

```bash
git add disney-pin-assistant/scripts/
git commit -m "feat: add vision quality test script for prompt tuning"
```

---

## Summary

| Task | Description | Depends On |
|------|-------------|------------|
| 1 | Project scaffolding | — |
| 2 | Database models | 1 |
| 3 | Pydantic schemas | 1 |
| 4 | Upload endpoint | 2, 3 |
| 5 | Vision extraction pipeline | 1 |
| 6 | Catalog matching | 2 |
| 7 | eBay comp search | 1 |
| 8 | Listing draft generation | 5, 6, 7 |
| 9 | Pipeline orchestrator | 2, 5, 6, 7, 8 |
| 10 | Pin CRUD and review actions | 2, 3, 4 |
| 11 | CSV export | 2, 10 |
| 12 | Web UI — upload page | 4, 9 |
| 13 | Web UI — queue and detail | 10, 12 |
| 14 | Catalog management endpoint | 2 |
| 15 | Integration test | 4, 9, 10, 11 |
| 16 | Catalog source evaluation | — |
| 17 | Vision prompt quality testing | 5 |
