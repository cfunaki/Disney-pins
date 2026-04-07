# Post-MVP Evaluation Plan

## Purpose

Define phased milestones for validating and iterating on the Disney Pin Listing Assistant after the MVP build. Each phase has a clear gate question — if it fails, the following phases are reconsidered before proceeding.

## Evaluation Strategy

Use 10-20 real pins sourced from a friend's existing eBay listings as the test batch. The friend's listings serve as ground truth: their photos are pipeline input, their titles/descriptions/prices are the benchmark to evaluate against.

---

## Phase 1A: Vision + Listing Quality

**Goal:** Determine if Claude Sonnet vision extraction correctly identifies pins and produces usable listing drafts.

**Prerequisites:**
- Register for Anthropic API access, obtain API key
- Configure `.env` with `ANTHROPIC_API_KEY`
- Collect 10-20 pin photos from friend's eBay account
- Record friend's listing titles, descriptions, and prices as ground truth reference

**Process:**
1. Upload pin photos as a batch
2. Run through vision extraction + listing draft generation (no catalog, no comps)
3. For each pin, compare AI output against friend's listing

**Evaluation dimensions:**
- **Identification accuracy:** Did the AI correctly identify the character, franchise, edition type, and pin type?
- **Listing quality:** Is the generated title/description comparable to the human-written version? Would it need minor edits or a full rewrite?

**Success criteria:**
- Vision extraction correctly identifies the pin in 80%+ of cases
- Generated listings need only minor edits (not full rewrites) for 70%+ of pins

**Output:** A scorecard (spreadsheet or markdown table) documenting per-pin results. Note patterns in what the AI gets right vs. wrong to inform vision prompt tuning.

**Gate question:** Is the AI extraction accurate enough to save time vs. writing listings manually?

---

## Phase 1B: Catalog Seeding

**Goal:** Seed the internal catalog and evaluate whether catalog matching improves identification and listing quality over vision-only extraction.

**Prerequisites:**
- Phase 1A passes (vision extraction is fundamentally viable)

**Process:**
1. Build a PinPics scraper with respectful rate limiting (1-2 req/sec)
2. Design and run the name normalization pipeline (capitalization, character names, edition size parsing)
3. Scrape an initial seed of 5,000-10,000 entries targeting:
   - Limited Edition pins (last 5 years)
   - Hidden Mickey pins (last 3 years)
   - Common rack pins (currently in parks)
   - Event-specific pins (Food & Wine, Halloween, etc.)
4. Import into the catalog via the existing CSV/JSON import endpoints
5. Re-run the same 10-20 test pins through the full pipeline (now with catalog matching active)
6. Compare: did catalog matching improve identification? Did listing quality improve?

**Evaluation dimensions:**
- **Match accuracy:** Does the correct catalog entry appear in the top 3 matches?
- **Listing improvement:** Are catalog-informed drafts better than vision-only drafts from Phase 1A?
- **Coverage:** What percentage of the test pins had a catalog match at all?

**Success criteria:**
- Correct catalog entry in top 3 for 70%+ of pins that have a catalog entry
- Catalog-matched listings are noticeably better than vision-only for matched pins

**Output:** Updated scorecard with catalog match results alongside Phase 1A vision-only results. Side-by-side comparison.

**Gate question:** Does catalog matching meaningfully improve listing quality over vision-only extraction?

---

## Phase 1C: Comp Search + Pricing

**Goal:** Validate that eBay comp search produces relevant results and pricing suggestions are in the right ballpark.

**Prerequisites:**
- Phase 1A passes
- Phase 1B complete (catalog-informed search terms available)
- Register for eBay developer account, obtain Browse API client ID and secret
- Configure `.env` with `EBAY_CLIENT_ID` and `EBAY_CLIENT_SECRET`

**Process:**
1. Run comp searches for the same 10-20 test pins using catalog-informed search terms
2. Review returned comps for relevance — are they the same pin? Are lots/bundles correctly filtered?
3. Compare suggested prices against friend's asking/sold prices

**Evaluation dimensions:**
- **Comp relevance:** Are the returned eBay results actually for the same pin?
- **Filter effectiveness:** Are lots, bundles, and unrelated listings correctly excluded?
- **Pricing accuracy:** Is the suggested price within a reasonable range of the reference price?

**Success criteria:**
- Comp searches return relevant results for 70%+ of pins
- Lot/bundle filtering correctly excludes irrelevant listings
- Suggested prices within 25% of reference prices for 70%+ of pins with comps

**Output:** Updated scorecard with pricing data. Note which pins had poor comps and why (rare pin, bad search terms, etc.).

**Gate question:** Is comp-based pricing reliable enough to be useful, or does the seller still need to manually research every price?

---

## Phase 2: Workflow Efficiency

**Goal:** Measure whether the tool actually saves time on a realistic batch.

**Prerequisites:**
- Phase 1A/1B/1C pass (pipeline produces acceptable output)
- Access to a larger set of pins (50-100)

**Process:**
1. Process a real batch of 50-100 pins end-to-end
2. Time the full workflow: upload, wait for processing, review each pin, approve/edit, export CSV
3. Track how many pins needed edits, what kind of edits, and how long each took
4. Compare total time against estimated manual listing time for the same pins

**Evaluation dimensions:**
- **End-to-end time:** How long from photo upload to exported CSV?
- **Edit rate:** What percentage of drafts needed manual corrections?
- **Bottlenecks:** Where does the user spend the most time? (processing wait, reviewing, editing, etc.)
- **UI friction:** Are there workflow pain points in the review queue or detail page?

**Success criteria:**
- Total listing time is at least 50% less than manual listing
- 60%+ of drafts are approvable with no or minor edits

**Output:** Timing data, edit rate statistics, list of UI improvements needed.

**Gate question:** Does this tool save enough time to justify continued investment?

---

## Phase 3: Multi-User + Deployment

**Goal:** Make the tool available to friends and remove manual export steps.

**Prerequisites:**
- Phase 2 passes (tool demonstrably saves time)

**Scope (to be designed in detail when Phase 2 completes):**
- Deploy to a hosted environment (cloud VPS or similar)
- Add user authentication (simple — small group of known users)
- Polish UI based on Phase 2 friction points
- Optionally: direct eBay API listing creation to replace CSV export
- Optionally: shared catalog that improves with each user's confirmed matches

**Gate question:** Is this reliable and polished enough for others to use without the builder present?

---

## Scorecard Template

For Phases 1A-1C, track per-pin results in a table like:

| Pin # | Photo | Friend's Title | AI Title | ID Correct? | Edits Needed | Catalog Match? | Match Rank | Comp Count | AI Price | Ref Price | Price Delta |
|-------|-------|---------------|----------|-------------|-------------|---------------|------------|------------|----------|-----------|-------------|
| 1 | pin1.jpg | ... | ... | Y/N | None/Minor/Major | Y/N | 1/2/3/- | N | $X | $Y | % |

This scorecard is the primary artifact for go/no-go decisions at each phase gate.
