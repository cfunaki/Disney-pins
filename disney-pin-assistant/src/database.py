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
