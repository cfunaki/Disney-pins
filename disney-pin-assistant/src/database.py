from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with async_session() as session:
        yield session


async def ensure_review_ui_columns(engine):
    """Idempotent migration for the human review UI feature."""
    async with engine.begin() as conn:
        result = await conn.execute(text("PRAGMA table_info(pins)"))
        existing_columns = {row[1] for row in result.fetchall()}
        if "no_catalog_match" not in existing_columns:
            await conn.execute(
                text("ALTER TABLE pins ADD COLUMN no_catalog_match BOOLEAN DEFAULT 0 NOT NULL")
            )


async def ensure_reference_label_columns(engine):
    """Idempotent migration for the pins-n-things reference-label columns."""
    new_columns = {
        "reference_source":          "TEXT",
        "reference_external_id":     "TEXT",
        "reference_url":             "TEXT",
        "reference_raw_title":       "TEXT",
        "reference_raw_description": "TEXT",
        "reference_parsed_fields":   "JSON",
        "reference_ingested_at":     "TEXT",
    }
    async with engine.begin() as conn:
        result = await conn.execute(text("PRAGMA table_info(pins)"))
        existing = {row[1] for row in result.fetchall()}
        for name, sql_type in new_columns.items():
            if name not in existing:
                await conn.execute(text(f"ALTER TABLE pins ADD COLUMN {name} {sql_type}"))


async def ensure_listing_collection_tables(engine):
    """Idempotent migration for ebay_listings and collection_jobs tables."""
    from src.models import Base
    async with engine.begin() as conn:
        # Check if tables exist; create only if missing
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='collection_jobs'")
        )
        if result.fetchone() is None:
            await conn.run_sync(
                lambda sync_conn: Base.metadata.tables["collection_jobs"].create(sync_conn, checkfirst=True)
            )
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='ebay_listings'")
        )
        if result.fetchone() is None:
            await conn.run_sync(
                lambda sync_conn: Base.metadata.tables["ebay_listings"].create(sync_conn, checkfirst=True)
            )


async def ensure_comp_weight_column(engine):
    """Idempotent migration: add `weight` column to `comps` table."""
    async with engine.begin() as conn:
        result = await conn.execute(text("PRAGMA table_info(comps)"))
        existing = {row[1] for row in result.fetchall()}
        if "weight" not in existing:
            await conn.execute(text("ALTER TABLE comps ADD COLUMN weight FLOAT"))
