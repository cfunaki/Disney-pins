from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="src/templates")

@router.get("/")
async def upload_page(request: Request):
    return templates.TemplateResponse(request, "upload.html")


@router.get("/queue/{batch_id}")
async def queue_page(request: Request, batch_id: str):
    return templates.TemplateResponse(request, "review.html", {"batch_id": batch_id})
