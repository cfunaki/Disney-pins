from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="src/templates")

@router.get("/")
async def upload_page(request: Request):
    return templates.TemplateResponse("upload.html", {"request": request})


@router.get("/queue/{batch_id}")
async def queue_page(request: Request, batch_id: str):
    return templates.TemplateResponse("queue.html", {"request": request, "batch_id": batch_id})


@router.get("/pins/{pin_id}")
async def detail_page(request: Request, pin_id: int):
    return templates.TemplateResponse("detail.html", {"request": request, "pin_id": pin_id, "batch_id": ""})
