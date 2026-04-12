---
description: "Find price comps for a pin from collected sold listings"
argument-hint: "<pin-id or search terms>"
allowed-tools: ["Bash", "Read", "Grep"]
---

Find price comparables for a pin by querying the `ebay_listings` table for sold listings with matching characteristics.

Parse the user's argument:
- If it's a number, treat it as a pin ID
- Otherwise treat it as search terms to find a pin by title

**Step 1: Identify the pin**

```
cd disney-pin-assistant && python -c "
import asyncio
from src.database import async_session
from sqlalchemy import select
from src.models import Pin

async def find_pin():
    async with async_session() as db:
        try:
            pin_id = int('$ARGUMENTS')
            result = await db.execute(select(Pin).where(Pin.id == pin_id))
        except ValueError:
            result = await db.execute(select(Pin).where(Pin.reference_raw_title.contains('$ARGUMENTS')).limit(5))
        pins = result.scalars().all()
        for p in pins:
            parsed = p.reference_parsed_fields or {}
            print(f'Pin {p.id}: {p.reference_raw_title}')
            print(f'  Characters: {parsed.get(\"characters\", \"unknown\")}')
            print(f'  Franchise: {parsed.get(\"franchise\", \"unknown\")}')
            print(f'  Edition: {parsed.get(\"edition_size\", \"unknown\")}')
            print()
asyncio.run(find_pin())
"
```

**Step 2: Find matching sold listings**

Using the pin's parsed fields (characters, franchise, edition_size), query sold listings:

```
cd disney-pin-assistant && python -c "
import asyncio, json
from src.database import async_session
from sqlalchemy import select
from src.models import Pin, EbayListing, EbayListingType

async def find_comps(pin_id):
    async with async_session() as db:
        pin = (await db.execute(select(Pin).where(Pin.id == pin_id))).scalars().first()
        if not pin:
            print('Pin not found')
            return
        parsed = pin.reference_parsed_fields or {}
        chars = set(parsed.get('characters', []))
        franchise = parsed.get('franchise', '')
        edition = parsed.get('edition_size')

        result = await db.execute(
            select(EbayListing).where(EbayListing.listing_type == EbayListingType.SOLD)
        )
        sold = result.scalars().all()

        scored = []
        for s in sold:
            sp = s.parsed_fields or {}
            score = 0
            s_chars = set(sp.get('characters', []))
            if chars and s_chars and chars & s_chars:
                score += 3
            if franchise and sp.get('franchise') == franchise:
                score += 2
            if edition and sp.get('edition_size') == edition:
                score += 2
            if score > 0:
                scored.append((score, s))

        scored.sort(key=lambda x: -x[0])
        if not scored:
            print('No matching sold listings found. Try collecting more sold data with /collect sold \"<keywords>\"')
            return

        print(f'Found {len(scored)} comps for: {pin.reference_raw_title}')
        print()
        prices = []
        for score, s in scored[:15]:
            prices.append(s.price)
            print(f'  \${s.price:.2f} | {s.sale_date or \"?\"} | {s.title[:60]} (score: {score})')
        if prices:
            print()
            print(f'  Avg: \${sum(prices)/len(prices):.2f} | Min: \${min(prices):.2f} | Max: \${max(prices):.2f} | Count: {len(scored)}')

asyncio.run(find_comps(<PIN_ID>))
"
```

Replace `<PIN_ID>` with the actual pin ID from step 1. If multiple pins matched, ask the user which one.

**Step 3: Summarize**

Present the comps in a table with price, date sold, title, and match score. Give a pricing recommendation based on the average and median of the top matches.

If no sold listings match, suggest running `/collect sold "<relevant keywords>"` to build up the sold data first.

User's input: $ARGUMENTS
