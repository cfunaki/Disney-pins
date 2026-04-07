from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Disney Pin Assistant")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/health")
async def health():
    return {"status": "ok"}
