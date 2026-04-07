from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from src.database import get_db, async_session
from src.models import Pin, PinStatus
from src.pipeline.orchestrator import process_batch

router = APIRouter(prefix="/api")

@router.post("/batch/{batch_id}/process")
async def start_batch_processing(batch_id: str, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(func.count(Pin.id)).where(Pin.batch_id == batch_id))
    total = result.scalar()
    if total == 0:
        return {"error": "No pins found for batch"}
    from src.database import async_session as session_factory
    background_tasks.add_task(process_batch, session_factory, batch_id)
    return {"batch_id": batch_id, "total": total, "status": "processing"}

@router.get("/batch/{batch_id}/progress")
async def batch_progress(batch_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Pin.status, func.count(Pin.id)).where(Pin.batch_id == batch_id).group_by(Pin.status))
    rows = result.all()
    status_counts = {status.value: count for status, count in rows}
    total = sum(status_counts.values())
    processed = total - status_counts.get("unprocessed", 0)
    return {"batch_id": batch_id, "total": total, "processed": processed, "status_counts": status_counts}
