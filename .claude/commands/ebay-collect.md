---
description: "Collect eBay listings (active or sold)"
argument-hint: "[active-seller <seller>] | [sold <query>] | [active-search <query>]"
allowed-tools: ["Bash", "Read", "Grep"]
---

Collect eBay listings into the `ebay_listings` table. Parse the user's argument to determine the subcommand:

- If the argument starts with "sold", run: `cd disney-pin-assistant && python scripts/collect_listings.py sold --query "<remaining args>" --no-parse`
- If the argument starts with "active-search", run: `cd disney-pin-assistant && python scripts/collect_listings.py active-search --query "<remaining args>" --no-parse`
- Otherwise treat the argument as a seller name and run: `cd disney-pin-assistant && python scripts/collect_listings.py active-seller --seller "<argument>" --query disney --no-parse`

After the collection completes:
1. Report the result summary (listings found, new, updated/skipped)
2. Query the database to show total collection stats:
   ```
   cd disney-pin-assistant && python -c "
   import asyncio
   from src.database import async_session
   from sqlalchemy import select, func
   from src.models import EbayListing, CollectionJob
   async def check():
       async with async_session() as db:
           jobs = (await db.execute(select(func.count()).select_from(CollectionJob))).scalar()
           listings = (await db.execute(select(func.count()).select_from(EbayListing))).scalar()
           print(f'Total jobs: {jobs}, Total listings: {listings}')
   asyncio.run(check())
   "
   ```
3. Ask if the user wants to run label parsing on the new listings (it costs Haiku API calls)

User's input: $ARGUMENTS
