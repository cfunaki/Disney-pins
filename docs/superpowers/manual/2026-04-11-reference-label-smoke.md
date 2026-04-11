# Reference Label Overlay — Manual Smoke Checklist

Scope: verify the new reference-label diff overlay renders correctly inside the existing human review UI. Run after any change to `static/review.js`, `static/style.css`, or `src/routes/pins.py:_pin_to_dict`.

## Setup

1. Ensure prod eBay keys and `ANTHROPIC_API_KEY` are set in `disney-pin-assistant/.env`.
2. Run `python scripts/import_ebay_seller.py --seller pins-n-things --batch-name pnt-smoke --max 5`.
3. Wait for the run to report `processing: enqueued` and the orchestrator to finish (tail the server log).
4. Open `http://localhost:8000/queue/pnt-smoke` in a browser.

## Checks

- [ ] The reference section appears **only** for pins that came from the ingest script. Any other batch shows no new section.
- [ ] On at least one pin, all diff rows show `✓` and the section is **collapsed** by default.
- [ ] On at least one pin, the section is **expanded** by default because it contains a `✗`.
- [ ] The raw title under the section header matches the actual eBay listing title.
- [ ] Clicking `↗ eBay` opens the real listing in a new tab.
- [ ] Characters render as a comma-separated list, booleans as `yes/no`, numeric fields as digits.
- [ ] No console errors in the browser devtools.
- [ ] Regression: normal uploads (manually uploaded pins) still render cleanly with no empty reference section.
