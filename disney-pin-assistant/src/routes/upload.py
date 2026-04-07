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
        safe_name = Path(file.filename).name  # strip path traversal
        file_path = upload_dir / safe_name
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
