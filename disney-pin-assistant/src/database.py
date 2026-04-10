from sqlalchemy import text
from sqlalchemy.exc import OperationalError
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
        try:
            await conn.execute(text("ALTER TABLE pins ADD COLUMN no_catalog_match BOOLEAN DEFAULT 0 NOT NULL"))
        except OperationalError:
            pass  # column already exists
