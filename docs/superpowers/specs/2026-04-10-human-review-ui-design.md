# Human Review UI — Design Spec

**Date:** 2026-04-10
**Status:** Approved (design phase)

## Goal

Replace the current minimal queue + detail pages with a focused two-pane review workspace that lets a single user (desktop) browse a batch, fix what the pipeline got wrong (match candidates, vision extraction, listing draft), and approve pins for export.

The current UI (`src/templates/queue.html`, `src/templates/detail.html`, `src/routes/pins.py`) supports approve/skip and basic listing-draft edits but has no way to:

- See which catalog candidates the matcher proposed
- Visually compare your photo against candidates
- Pick a different match than the matcher's top choice
- Edit the vision extraction and re-run matching
- Surface *why* a pin is risky (ambiguous match vs. low extraction confidence vs. no match at all)

This spec covers the UI overhaul, the new API endpoints behind it, and the cascade rules for re-matching and draft regeneration.

## Workflow assumptions

- **Single user**, desktop only. No multi-user concurrency, no mobile/tablet.
- **Browse-and-cherry-pick**, not power-user blast mode. The user scans the queue, clicks the risky ones, fixes them, moves on. Auto-advance and aggressive keyboard shortcuts are out of scope.
- Batches are typically tens of pins, not hundreds.

## Architecture

### Pages

A single new template `src/templates/review.html` replaces both `queue.html` and `detail.html`. The route `/queue/{batch_id}` serves it.

### Two-pane layout

```
┌────────────────────────────────────────────────────────────┐
│ Header: batch id · pin counts · approved counter           │
├──────────────────┬─────────────────────────────────────────┤
│ Queue list       │ Detail pane                             │
│ (38% width)      │ (flex 1)                                │
│                  │                                         │
│ - filter input   │ Header: pin name · risk reason · Approve│
│ - sort dropdown  │                                         │
│ - scrollable     │ Section 1 — Match Review                │
│   list of pins   │ Section 2 — Vision Extraction           │
│   with thumbnail,│ Section 3 — Listing Draft               │
│   title,         │                                         │
│   risk badge,    │                                         │
│   price          │                                         │
└──────────────────┴─────────────────────────────────────────┘
```

Click a pin row in the left pane → right pane swaps to that pin's detail. No page navigation between pins.

### Queue list (left pane)

Each row: thumbnail (48px) · title (truncated) · risk badge · price.

**Risk badges** replace raw confidence numbers as the primary signal:

- `✓ ready` — high confidence match, draft ready, no flags
- `⚠ ambiguous match` — top match score < 0.9 OR gap to #2 < 0.1 (the same threshold the existing vision-confirm uses)
- `⚠ low extraction` — vision extraction confidence below 0.6
- `✗ no match` — matcher returned nothing OR user marked it "no match in catalog"
- `→ exported` — already exported
- `✓ approved` — approved but not yet exported

A pin can show one badge — the most severe wins (no match > ambiguous > low extraction > approved > ready).

**Sort** (default: Risk descending — risky pins float to the top): Risk, Price, Status, Order added.

**Filter**: free-text input that matches against pin title and characters.

### Detail pane

Header: pin id, current pin name (from accepted match if any, else top candidate, else "(unknown)"), risk explanation, Approve and Skip buttons.

Three stacked sections, each in its own bordered card.

#### Section 1 — Match Review

The most important section.

- **Side-by-side compare row**: user's photo on the left, currently-selected catalog candidate on the right (large, ~240px tall). Selected candidate shows score, canonical name, source (PinTradingDB), edition size, and release year.
- **Action buttons** below the compare row: ✓ Accept this match (green), ✗ None of these (red), 🔍 Search catalog… (neutral).
- **Top 5 candidate strip**: horizontal scrollable row of cards with thumbnail, letter (A–E), score, and short name. Click a card → it loads into the compare slot. The currently-selected one has a highlight border.
- **Risk explanation banner** at the bottom (when ambiguous): "A and B are within 0.02 — visually very similar pins. Vision-confirm picked B based on the back stamp." Pulled from the matcher's existing reasoning fields.

If the matcher returned no candidates: empty state with the two action buttons (None of these, Search catalog) and an instruction to edit extraction and re-match.

#### Section 2 — Vision Extraction

Editable form with the fields most likely to be wrong: characters, franchise, pin type, edition size, visible dates, event clues. (Other extraction fields stay read-only — they're rarely the cause of a bad match.)

- Vision confidence shown read-only.
- Single button: **💾 Save & Re-match**. Re-match is explicit (not auto on field change) because it's expensive.

#### Section 3 — Listing Draft

Editable form: title (max 80), description, suggested price, quick sale price, tags. Price confidence shown read-only.

- Blue banner at the top when the draft was just auto-regenerated: "↻ Auto-regenerated from accepted match (Mickey 50th — Cast Member Excl.)"
- Two buttons: **↻ Regenerate from match** (manual override), **💾 Save draft**.

### Cascade rules

- **Accept a different catalog match** → listing draft auto-regenerates from the new catalog entry. Cheap (no API calls), happens immediately.
- **Edit extraction → Save & Re-match** → server re-runs matcher. UI shows a spinner over the match section only; rest of the UI stays interactive. New candidates replace old ones. The draft does **not** auto-regenerate at this point — only when the user accepts a candidate from the new list.
- **Mark "None of these"** → server generates a listing draft from extraction alone (skipping any catalog match). Draft section refreshes.
- **Approve while draft is dirty** → save first, then approve. No confirm dialog.

## API surface

New endpoints:

- `GET /api/catalog/search?q=...&offset=0` — name/character search for the "Search catalog…" button. Returns top 20 catalog entries with id, canonical name, thumbnail path, release year, edition size. `offset` supports the "load more" button.
- `POST /api/pins/{id}/match/select` — body `{catalog_entry_id}`. Marks the chosen `CatalogMatch` as `ACCEPTED` and others as `REJECTED`. Triggers listing-draft regeneration from the new catalog entry. Returns the updated pin dict.
- `POST /api/pins/{id}/match/none` — marks all candidates as `REJECTED`, sets a flag/note that this pin has no catalog match, generates a listing draft from extraction. Returns the updated pin dict.
- `POST /api/pins/{id}/extraction` — patch extraction fields (characters, franchise, pin_type, edition_size, visible_dates, event_clues). Persists to `VisionExtraction`. Returns the updated pin dict. Does not re-match.
- `POST /api/pins/{id}/rematch` — re-runs the matcher with the current extraction. Replaces existing `CatalogMatch` rows for this pin. Returns the new candidate list. Does not regenerate the draft (waiting for user to accept one).
- `POST /api/pins/{id}/draft/regenerate` — manual override. Regenerates the listing draft from the currently accepted match (or from extraction if none accepted). Returns the new draft.

Existing `GET /api/pins/{id}` (`src/routes/pins.py:19`) is extended so each entry in `catalog_matches` includes `canonical_name`, `image_path`, `release_year`, `edition_size`, and `source` — pulled from the joined `CatalogEntry`. This avoids per-candidate round trips.

Existing `GET /api/batch/{batch_id}/pins` is extended to include the data needed for the queue list rows: top match's canonical name, risk badge classification (computed server-side), and the pin's accepted match if any.

## Data model changes

Minimal — the existing schema in `src/models.py` already supports almost everything.

One small addition: a way to record "no catalog match" explicitly. Options:

1. Add a `no_catalog_match` boolean to `Pin`.
2. Use the existing `Pin.seller_notes` field with a marker (matches the current "skip" pattern at `src/routes/pins.py:47`).
3. Add a new `PinStatus` enum value `NO_MATCH`.

**Decision: option 1.** Cleanest, queryable, doesn't overload `seller_notes`. Add `no_catalog_match: bool = False` to `Pin`. Migration: SQLite `ALTER TABLE` add column with default `0`.

## Frontend architecture

- Stay vanilla JS — no framework. Single user, small surface.
- Replace `queue.html` and `detail.html` with one template `review.html`.
- Split `static/app.js`: keep upload logic in `app.js`, add `static/review.js` for the workspace.
- `review.js` holds in-memory state: `{ batchId, pins: [...], selectedPinId, dirty: false }`.
- Mutations: API call → update local pin object → re-render only the affected scoped DOM container (not full reload, no scroll loss).
- Minimal keyboard: `↑/↓` navigate the queue list, `Enter` approve. No more.

## Edge cases

1. **Re-match in flight, user clicks another pin** — request keeps going server-side. When it returns, results attach to that pin's state and a toast shows "Pin #142 re-matched."
2. **No candidates at all** — match section shows empty state with the two action buttons and instructions.
3. **Search returns thousands** — paginated, top 20 by name relevance, "load more" button. No infinite scroll.
4. **Image fails to load** — placeholder div with the canonical name (extends pattern from current detail page).
5. **Approve while draft is dirty** — save first, then approve. No confirm dialog.
6. **Concurrent edits** — single user assumption. Last write wins. No locking.

## Testing

Narrow on purpose — this is mostly UI work.

1. **API tests** (pytest, async) — one per new endpoint in `tests/`. Cover the side effects: select-match writes correct `MatchStatus` rows AND triggers draft regeneration; none-match generates draft from extraction; re-match replaces old candidates.
2. **Pipeline integration test** — one end-to-end test: upload → extract → match → user accepts a non-top match via the API → assert listing draft was regenerated using the new catalog entry's data.
3. **No frontend tests** — vanilla JS, single user. Manual click-through is sufficient.
4. **Manual smoke checklist** committed to the repo (10 steps): upload a batch, click a risky pin, accept a different candidate, edit extraction and re-match, mark "no match", approve, verify export still works.

## Out of scope

- Mobile / tablet layouts.
- Multi-user concurrency, locks, or auth changes.
- Power-user blast mode (one-pin-per-screen, aggressive keyboard shortcuts).
- Reordering or renaming the existing pipeline stages.
- Touching the scraper, the matcher, or the vision extractor — only their outputs are consumed.
- eBay comps integration (still blocked on credentials).

## Files affected

- `src/templates/review.html` — new (replaces `queue.html` and `detail.html`)
- `src/templates/queue.html` — delete
- `src/templates/detail.html` — delete
- `src/routes/pages.py` — update `/queue/{batch_id}` to render `review.html`; remove `/pins/{pin_id}` page route (still served as data via `/api/pins/{id}`)
- `src/routes/pins.py` — extend `_pin_to_dict`, add new endpoints
- `src/routes/catalog.py` — add catalog search endpoint
- `src/models.py` — add `Pin.no_catalog_match` column + migration
- `src/pipeline/listing.py` — expose a function that takes a `Pin` and regenerates its draft (called by select-match, none-match, and the manual regenerate endpoint)
- `static/review.js` — new
- `static/style.css` — new styles for two-pane layout, candidate strip, risk badges
- `tests/` — new tests for the API endpoints and the integration test
