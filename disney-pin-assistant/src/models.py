import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    Text,
    ForeignKey,
    Enum,
    JSON,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ── Enums ──────────────────────────────────────────────────────────────


class PinStatus(str, enum.Enum):
    UNPROCESSED = "unprocessed"
    EXTRACTED = "extracted"
    MATCHED = "matched"
    PRICED = "priced"
    APPROVED = "approved"
    EXPORTED = "exported"
    ERROR = "error"


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


# ── Helper ─────────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Tables ─────────────────────────────────────────────────────────────


class Pin(Base):
    __tablename__ = "pins"

    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(String(100), nullable=False)
    status = Column(Enum(PinStatus), nullable=False, default=PinStatus.UNPROCESSED)
    photo_type = Column(String(50), nullable=True)
    seller_notes = Column(Text, nullable=True)
    image_paths = Column(JSON, default=list)
    created_at = Column(String, default=lambda: _utcnow().isoformat())
    updated_at = Column(String, default=lambda: _utcnow().isoformat(), onupdate=lambda: _utcnow().isoformat())

    # Relationships
    extraction = relationship("VisionExtraction", back_populates="pin", uselist=False)
    catalog_matches = relationship("CatalogMatch", back_populates="pin")
    comps = relationship("Comp", back_populates="pin")
    listing_draft = relationship("ListingDraft", back_populates="pin", uselist=False)


class VisionExtraction(Base):
    __tablename__ = "vision_extractions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pin_id = Column(Integer, ForeignKey("pins.id"), nullable=False)
    characters = Column(JSON, default=list)
    franchise = Column(String(200), nullable=True)
    collection_or_series = Column(String(200), nullable=True)
    text_on_pin = Column(Text, nullable=True)
    visible_dates = Column(String(200), nullable=True)
    event_clues = Column(Text, nullable=True)
    pin_type = Column(String(100), nullable=True)
    edition_size = Column(Integer, nullable=True)
    condition_observations = Column(Text, nullable=True)
    suggested_search_terms = Column(JSON, default=list)
    confidence_score = Column(Float, nullable=False)
    raw_api_response = Column(JSON, nullable=True)
    created_at = Column(String, default=lambda: _utcnow().isoformat())

    # Relationships
    pin = relationship("Pin", back_populates="extraction")


class CatalogEntry(Base):
    __tablename__ = "catalog_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    canonical_name = Column(String(500), nullable=False)
    alternate_names = Column(JSON, default=list)
    characters = Column(JSON, default=list)
    franchise = Column(String(200), nullable=True)
    series_or_collection = Column(String(200), nullable=True)
    event = Column(String(200), nullable=True)
    edition_size = Column(Integer, nullable=True)
    release_year = Column(Integer, nullable=True)
    pin_type = Column(String(100), nullable=True)
    exclusive_source = Column(String(200), nullable=True)
    source = Column(String(100), nullable=True)
    source_reference_id = Column(String(100), nullable=True)
    reference_image_url = Column(String(500), nullable=True)
    image_path = Column(String(500), nullable=True)        # Local path to downloaded image
    clip_embedding = Column(Text, nullable=True)           # JSON-serialized float list (512 dims)
    evidence_strength = Column(String(20), default="low")
    created_at = Column(String, default=lambda: _utcnow().isoformat())
    updated_at = Column(String, default=lambda: _utcnow().isoformat(), onupdate=lambda: _utcnow().isoformat())

    # Relationships
    matches = relationship("CatalogMatch", back_populates="catalog_entry")


class CatalogMatch(Base):
    __tablename__ = "catalog_matches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pin_id = Column(Integer, ForeignKey("pins.id"), nullable=False)
    catalog_entry_id = Column(Integer, ForeignKey("catalog_entries.id"), nullable=False)
    match_confidence = Column(Float, nullable=False)
    match_reasoning = Column(Text, nullable=True)
    rank = Column(Integer, default=1)
    status = Column(Enum(MatchStatus), nullable=False, default=MatchStatus.SUGGESTED)
    created_at = Column(String, default=lambda: _utcnow().isoformat())

    # Relationships
    pin = relationship("Pin", back_populates="catalog_matches")
    catalog_entry = relationship("CatalogEntry", back_populates="matches")


class Comp(Base):
    __tablename__ = "comps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pin_id = Column(Integer, ForeignKey("pins.id"), nullable=False)
    ebay_listing_id = Column(String(50), nullable=True)
    title = Column(String(500), nullable=False)
    price = Column(Float, nullable=False)
    sale_date = Column(String(20), nullable=True)
    listing_type = Column(Enum(ListingType), nullable=False)
    condition = Column(String(50), nullable=True)
    match_type = Column(Enum(MatchType), default=MatchType.NEAR)
    excluded = Column(Boolean, default=False)
    exclusion_reason = Column(String(200), nullable=True)
    raw_data = Column(JSON, nullable=True)
    fetched_at = Column(String, default=lambda: _utcnow().isoformat())

    # Relationships
    pin = relationship("Pin", back_populates="comps")


class ListingDraft(Base):
    __tablename__ = "listing_drafts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pin_id = Column(Integer, ForeignKey("pins.id"), nullable=False)
    title = Column(String(80), nullable=False)
    description = Column(Text, nullable=True)
    item_specifics = Column(JSON, nullable=True)
    suggested_price = Column(Float, nullable=True)
    quick_sale_price = Column(Float, nullable=True)
    price_confidence = Column(String(20), default="low")
    pricing_reasoning = Column(Text, nullable=True)
    category_suggestion = Column(String(200), nullable=True)
    tags_keywords = Column(JSON, default=list)
    export_status = Column(Enum(ExportStatus), nullable=False, default=ExportStatus.DRAFT)
    seller_edits = Column(JSON, nullable=True)
    created_at = Column(String, default=lambda: _utcnow().isoformat())
    updated_at = Column(String, default=lambda: _utcnow().isoformat(), onupdate=lambda: _utcnow().isoformat())

    # Relationships
    pin = relationship("Pin", back_populates="listing_draft")
