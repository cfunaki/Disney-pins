---
description: "Ingest a seller's full catalog: collect, promote, and process"
argument-hint: "<seller-name> [batch-name]"
allowed-tools: ["Bash", "Read", "Grep"]
---

Full ingest pipeline for a seller's eBay listings. This combines collection, promotion to pins, and pipeline processing in one shot.

Parse the user's argument: first word is the seller name, optional second word is the batch name (default: `<seller>-YYYY-MM-DD`).

Steps:

1. **Collect active listings** from the seller:
   ```
   cd disney-pin-assistant && python scripts/collect_listings.py active-seller --seller "<seller>" --query disney
   ```
   (Include label parsing by default — no `--no-parse` flag)

2. Report collection results.

3. **Promote to pins** using the job ID from step 1:
   ```
   cd disney-pin-assistant && python -c "
   import asyncio
   from src.database import async_session
   from sqlalchemy import select, func
   from src.models import CollectionJob
   async def get_latest():
       async with async_session() as db:
           result = await db.execute(select(CollectionJob).order_by(CollectionJob.id.desc()).limit(1))
           job = result.scalars().first()
           print(job.id if job else 'none')
   asyncio.run(get_latest())
   "
   ```
   Then:
   ```
   cd disney-pin-assistant && python scripts/collect_listings.py promote --job-id <JOB_ID> --batch-name "<batch-name>"
   ```

4. Report promotion results.

5. Ask the user if they want to run the vision/match/price pipeline on the new pins. If yes:
   ```
   cd disney-pin-assistant && python -c "
   import asyncio
   from src.database import async_session
   from src.pipeline.orchestrator import process_batch
   asyncio.run(process_batch(async_session, '<batch-name>'))
   "
   ```

User's input: $ARGUMENTS
