from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from src.config import settings
from src.database import engine
from src.models import Base
from src.routes.upload import router as upload_router
from src.routes.processing import router as processing_router
from src.routes.pins import router as pins_router
from src.routes.export import router as export_router
from src.routes.catalog import router as catalog_router
from src.routes.pages import router as pages_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield

app = FastAPI(title="Disney Pin Assistant", lifespan=lifespan)
settings.upload_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(settings.upload_dir)), name="uploads")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(upload_router)
app.include_router(processing_router)
app.include_router(pins_router)
app.include_router(export_router)
app.include_router(catalog_router)
app.include_router(pages_router)

@app.get("/health")
async def health():
    return {"status": "ok"}
