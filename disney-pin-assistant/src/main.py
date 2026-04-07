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
