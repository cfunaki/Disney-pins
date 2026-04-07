import csv
import io
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from src.database import get_db
from src.models import Pin, PinStatus, ListingDraft, ExportStatus

router = APIRouter(prefix="/api")

CSV_COLUMNS = ["Title", "Description", "Price", "Quick Sale Price", "Price Confidence", "Category", "Tags", "Brand", "Character", "Franchise", "Type", "Edition Size", "Year"]

@router.get("/batch/{batch_id}/export")
async def export_batch_csv(batch_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Pin).options(selectinload(Pin.listing_draft)).where(Pin.batch_id == batch_id, Pin.status == PinStatus.APPROVED)
    )
    pins = result.scalars().all()
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for pin in pins:
        draft = pin.listing_draft
        if not draft:
            continue
        specifics = draft.item_specifics or {}
        writer.writerow({
            "Title": draft.title, "Description": draft.description or "",
            "Price": draft.suggested_price, "Quick Sale Price": draft.quick_sale_price,
            "Price Confidence": draft.price_confidence, "Category": draft.category_suggestion or "",
            "Tags": ", ".join(draft.tags_keywords or []),
            "Brand": specifics.get("Brand", ""), "Character": specifics.get("Character", ""),
            "Franchise": specifics.get("Franchise", ""), "Type": specifics.get("Type", ""),
            "Edition Size": specifics.get("Edition Size", ""), "Year": specifics.get("Year", ""),
        })
    for pin in pins:
        if pin.listing_draft:
            pin.listing_draft.export_status = ExportStatus.EXPORTED
        pin.status = PinStatus.EXPORTED
    await db.commit()
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={batch_id}-listings.csv"},
    )
