# Disney Pin Listing Assistant — Design Spec

## Overview

A focused listing preparation tool for Disney pin sellers. Takes batch pin photos and produces reviewed, export-ready eBay listing drafts with AI-powered identification, catalog matching, and comp-based pricing.

**Scope:** Phase 0 (Discovery) + Phase 1 (MVP), combined via a full-stack vertical slice approach — discovery work happens during the build, not as a separate phase.

**Users:** Single user (you), running locally. Designed for future deployment and multi-user support.

## Product Thesis

The winning product is a category-aware listing preparation assistant for Disney pins, with image-assisted identification and comp-based pricing. The moat is built from structured pin metadata, matching logic across community catalogs and marketplace evidence, comp ranking, and workflow efficiency.

eBay remains the selling platform and system of record. We build custom tooling only for the category-specific work that eBay and generic reseller tools do poorly.

## Guiding Principles

1. **Human-in-the-loop is mandatory.** Pins are too nuanced for blind automation. The system reduces work and surfaces best guesses; it does not pretend to be certain.
2. **Confidence matters more than breadth.** Right 85-90% of the time with clear uncertainty flags beats "answers everything" with frequent errors.
3. **Batch workflow is the key UX.** Optimized for processing 20-200 pins at a time, not one-at-a-time interactions.
4. **Category-specific data is the differentiator.** Pin naming inconsistency, set vs individual ambiguity, visual lookalikes, edition-specific pricing — generic tools can't solve these.

## Tech Stack

- **Backend:** Python, FastAPI
- **Frontend:** Simple HTML/JS served by the backend
- **Database:** SQLite (swappable to Postgres at deployment)
- **File storage:** Local directory (swappable to S3 at deployment)
- **AI:** Anthropic Claude Sonnet API for vision extraction
- **Comps:** eBay Browse API + Taxonomy API
- **Catalog:** Internal SQLite table, seeded from community source(s)

## System Architecture

Three layers:

### 1. Web Frontend
Simple HTML/JS served by FastAPI. Table-based review queue. Upload form for photos. Inline editing of results.

### 2. FastAPI Backend
Handles uploads, orchestrates the processing pipeline, serves the UI, exposes REST endpoints for the frontend.

### 3. Processing Pipeline
The core intelligence, broken into sequential steps per pin, with pins processed in parallel (concurrency-limited for API rate management):

1. **Image Ingestion** — Accept photos, store locally, seller tags photo type (front, backstamp, group, unknown)
2. **Vision Extraction** — Claude Sonnet API call, returns structured JSON
3. **Catalog Matching** — Search internal catalog for ranked candidates
4. **eBay Comp Search** — Search eBay API for sold/active listings, filter and rank
5. **Listing Generation** — Combine into title, description, tags, price recommendation

## Data Model

### pins
The central record for each pin being processed.
- id (auto-generated internal ID)
- batch_id (groups pins from the same upload session)
- status: unprocessed → extracted → matched → priced → approved → exported
- photo_type: front, backstamp, group, unknown
- seller_notes (optional free text)
- image_paths (list of file paths to uploaded photos)
- created_at, updated_at

### vision_extractions
What Claude sees in the image.
- id, pin_id (FK)
- characters (list)
- franchise (e.g., "Mickey & Friends", "Star Wars", "Marvel")
- collection_or_series
- text_on_pin
- visible_dates
- event_clues
- pin_type (enamel, limited edition, mystery, rack, hidden mickey, etc.)
- edition_size (if detected)
- condition_observations
- suggested_search_terms (list)
- confidence_score (0-1)
- raw_api_response (JSON, stored for debugging)
- created_at

### catalog_entries
The internal pin reference catalog.
- id
- canonical_name
- alternate_names (list)
- characters (list)
- franchise
- series_or_collection
- event
- edition_size
- release_year
- pin_type
- exclusive_source (e.g., "Walt Disney World", "Disneyland", "shopDisney")
- source (which community database this came from)
- source_reference_id (e.g., PinPics number)
- reference_image_url
- evidence_strength (low, medium, high)
- created_at, updated_at

### catalog_matches
Links a pin to candidate catalog entries.
- id, pin_id (FK), catalog_entry_id (FK)
- match_confidence (0-1)
- match_reasoning (text explaining why this was suggested)
- rank (1 = best candidate)
- status: suggested → accepted / rejected
- created_at

### comps
eBay comparable sales data.
- id, pin_id (FK)
- ebay_listing_id
- title
- price
- sale_date
- listing_type: sold / active
- condition
- match_type: exact / near
- excluded (boolean)
- exclusion_reason (lot/bundle, wrong variant, etc.)
- raw_data (JSON)
- fetched_at

### listing_drafts
The generated output.
- id, pin_id (FK)
- title (max ~80 chars, eBay optimized)
- description
- item_specifics (JSON)
- suggested_price
- quick_sale_price
- price_confidence (low, medium, high)
- pricing_reasoning
- category_suggestion
- tags_keywords (list)
- export_status: draft → approved → exported
- seller_edits (JSON, tracks what was changed)
- created_at, updated_at

## Processing Pipeline Detail

### Step 1: Upload & Ingest
- Seller drops photos into upload form
- Optionally tags photo types (front, backstamp, group) or leaves as "unknown"
- Group photos flagged for the seller to re-upload as individual pin photos (no in-app cropping tool in MVP)
- Pin record created with status "unprocessed"

### Step 2: Vision Extraction (async with progress)
- Each pin's photos sent to Claude Sonnet in a single API call
- Prompt requests structured JSON output: characters, franchise, text on pin, edition clues, pin type, condition notes, suggested search terms
- Results stored in vision_extractions
- Pin status → "extracted"
- Frontend shows results streaming in as each pin completes

### Step 3: Catalog Matching
- Extracted metadata searched against catalog_entries
- Matching uses: character overlap, franchise, edition keywords, series name, event name
- Ranked by number of matching attributes, weighted by specificity (edition number match > character match)
- Top 3 candidates returned with confidence and reasoning
- Pin status → "matched" (or stays "extracted" if no good candidates found)

### Step 4: eBay Comp Search
- Search eBay Browse API using: best match's canonical name + extracted keywords
- Filter by eBay category (Collectibles > Disney > Pins)
- Pull both sold (last 90 days) and active listings
- Filter out: lots/bundles, wrong variants, obvious mismatches
- Rank by relevance and recency
- Compute: median sold price, price range, comp count
- Store raw results for future filtering refinement
- Pin status → "priced"

### Step 5: Listing Draft Generation
- Combine identification + comps into listing draft
- Title: key details front-loaded, ~80 chars, eBay best practices
- Description: concise, highlights edition/event/condition
- Price recommendation: market rate + quick-sale price + confidence level
- Pin status stays "priced" until seller reviews

### Step 6: Seller Review
- Review queue table shows all pins in batch
- Each row: thumbnail, suggested title, description, tags, confidence, price, comps summary
- Click into row for detail view: all candidate matches, comp listings, inline field editing
- Actions: approve, edit, reject match (pick alternate), skip, flag as unknown
- Approved items available for CSV export

### Concurrency Model
- Pins processed in parallel through the full pipeline (steps 2-5)
- Concurrency limit on API calls (configurable, default ~5 concurrent)
- Progress shown in UI as each pin completes each step

## eBay API Integration

### APIs Used
- **Browse API** — Search sold and active listings by keyword. Returns title, price, condition, images, sale date.
- **Taxonomy API** — Get correct eBay category IDs for Disney pins.

### Setup Required
- Register at developer.ebay.com
- Create application for API keys (client ID + client secret)
- OAuth client credentials flow (no user login needed for search)

### Comp Search Strategy
- Primary search: canonical pin name from catalog match
- Fallback: extracted keywords if no catalog match
- Filter by eBay category to reduce noise
- Pull sold (last 90 days) + active listings
- Store raw results for filtering refinement without re-fetching

### Rate Limits
- eBay Browse API: 5,000 calls/day on basic account
- ~2 calls per pin (sold + active) = 2,500 pins/day capacity

### NOT in MVP
- Trading API / Inventory API (for creating listings)
- User-level OAuth (seller authorization)
- Live listing sync

## Catalog Strategy

### Seeding
- During discovery, evaluate community sources (PinPics and others) for data quality and accessibility
- If viable, one-time import to seed catalog_entries table
- Each entry tagged with source and evidence_strength

### Matching Logic
- Query catalog using: character names, franchise, event keywords, edition info, text on pin
- Rank by number of matching attributes, weighted by specificity
- Top 3 candidates with confidence and reasoning

### Growth Over Time
- Seller-confirmed matches and manual identifications feed back into catalog
- New entries created for pins not in catalog
- Existing entries enriched with alternate names and better metadata
- Data accumulates from day one for future learning improvements

### Discovery Deliverables
- Which community source(s) are viable to seed from
- How much manual cleanup imported data needs
- Coverage gap assessment (what percentage of common pins are represented)

## Web UI

### Batch Upload View
- Drag-and-drop or file picker for multiple photos
- Option to tag photo types per image
- "Process Batch" button
- Progress indicator showing per-pin status

### Review Queue (main view)
- Table with columns: thumbnail, title, confidence, price recommendation, status
- Sortable/filterable by status and confidence
- Batch actions: approve all high-confidence, export approved

### Pin Detail View (click into a row)
- Large image display
- Vision extraction results
- Candidate matches with reasoning (accept/reject per candidate)
- Comp listings with prices and dates
- Editable fields: title, description, price, tags
- Approve / skip / flag buttons

### Review States
- unprocessed → extracted → matched → priced → approved → exported
- "needs review" flag for low-confidence items

## MVP Scope Boundary

### In Scope
- Catalog source evaluation and seeding (discovery)
- Claude vision quality testing on real pins (discovery)
- Metadata schema (defined as database models)
- FastAPI backend with SQLite
- Photo upload with type tagging
- Async batch processing with progress tracking
- Claude Sonnet vision extraction
- Internal pin catalog with community source seeding
- Catalog matching with ranked candidates
- eBay Browse API comp search
- Comp filtering and pricing recommendation
- Listing draft generation
- Web UI: upload, review queue, detail view, inline editing
- Approve/edit/skip/flag workflow
- CSV export of approved listings
- Single user, local hosting

### Out of Scope
- User accounts / authentication
- Direct eBay API listing creation
- Auto-cropping of group photos
- Inventory management / live listing tracking
- Sale result sync from eBay
- Cloud deployment / hosting
- Feedback-driven model retraining
- Multi-category collectibles support
- Shipping, accounting, CRM

## Cost Estimates

### API Costs (per batch of 100 pins)
- Claude Sonnet vision: ~$0.50
- eBay Browse API: free (within 5,000/day limit)
- Monthly estimate at a few batches/week: $5-10

### Infrastructure (MVP)
- None — runs locally
- Future deployment: ~$5-20/month for a small VPS or platform host

## Testing and Validation

### Vision Extraction Quality
- Assemble a sample set of 20-30 real pin photos covering common types (rack pins, limited editions, mystery pins, event exclusives)
- Run Claude Sonnet against each, manually grade output on: character identification accuracy, text reading accuracy, edition/event clue detection, pin type classification
- Use results to tune the vision prompt before building the full pipeline
- Target: 80%+ of extractions are usable without major corrections

### Catalog Matching Accuracy
- After seeding the catalog, select 20+ pins where you already know the correct identity
- Run the matching logic and check: does the correct catalog entry appear in the top 3 candidates?
- Measure: match rate at rank 1, match rate in top 3, false positive rate
- Target: correct entry in top 3 for 70%+ of pins that exist in the catalog

### Comp Relevance
- For 10-15 pins with known market value, run the eBay comp search
- Manually check: are returned comps actually the same or similar pin? Are bundles/lots filtered out? Are wrong variants excluded?
- Spot-check the filtering logic against edge cases (sets listed as singles, scrappers, different editions)
- Target: 80%+ of returned comps are genuinely relevant

### End-to-End Batch Test
- Process a real batch of 30-50 pins through the full pipeline
- Review complete output: identification, matching, comps, pricing, draft listing
- Measure: how many listings are usable without major edits, total time from upload to approved drafts
- Compare against estimated manual time for the same batch

### Unit Tests
- API endpoint tests: upload, processing status, review actions, export
- Database operations: CRUD on all tables, status transitions
- Comp filtering logic: verify bundles/lots are excluded, wrong variants filtered
- Matching ranking logic: verify weighting produces correct ordering
- Listing generation: verify title length limits, required fields present

### Not in MVP Testing Scope
- Automated frontend/browser tests (manual testing sufficient for single-user UI)
- Load/performance testing
- Security testing (single user, local only)

## Success Criteria

The MVP is successful if:
1. Uploading and processing a batch of 50+ pins works end-to-end
2. Vision extraction produces useful, accurate metadata for 80%+ of common pins
3. Catalog matching surfaces relevant candidates that reduce manual lookup time
4. eBay comps return usable pricing data for most pins
5. Total time from photo upload to approved listing draft is materially faster than the current manual process
6. The tool is something you'd voluntarily use for real batches

## Future Phases (out of scope, for context)

- **Phase 2:** Advanced matching — better ranking, visual similarity, broader catalog
- **Phase 3:** Smarter comp engine — near-match comp logic, pricing confidence improvements
- **Phase 4:** eBay API publishing — direct listing creation from approved drafts
- **Phase 5:** Learning system — feedback loops, accuracy improvement from usage data
- **Phase 6:** Advanced automation — markdown suggestions, bundle recommendations, category expansion
