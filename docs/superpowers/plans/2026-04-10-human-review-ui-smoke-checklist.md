# Human Review UI — Manual Smoke Checklist

Walk through this list after any change touching the review workspace, the new endpoints, or the draft regeneration helper.

1. [ ] Upload a small batch (3–5 pins) via the home page; wait for processing to complete.
2. [ ] Open `/queue/<batch-id>` — two-pane layout renders, queue list shows all pins with thumbnails, badges, and prices.
3. [ ] Click a row → right pane loads with header, match review, extraction, and draft sections.
4. [ ] Click a different candidate card in the strip → compare slot updates with the new image and metadata.
5. [ ] Click "✓ Accept this match" with the second candidate selected → pin updates, draft auto-regenerates, queue badge changes.
6. [ ] Edit a field in the extraction form (e.g., Characters) → click "💾 Save & Re-match" → spinner button text appears, then candidate strip refreshes.
7. [ ] On a different pin, click "✗ None of these" → pin gets the no-match badge, draft regenerates from extraction only.
8. [ ] Click "🔍 Search catalog…" → modal opens, type a query, click "Use this" on a result → modal closes, pin updates with the manually picked match.
9. [ ] Click "↻ Regenerate from match" in the draft section → draft refreshes.
10. [ ] Click "Approve" in the header → pin status flips to approved, queue counts increment, badge updates.
11. [ ] Use ↑/↓ to navigate the queue and Enter to approve — keyboard shortcuts work outside of input fields.
12. [ ] Verify the existing CSV export still works at `/api/batch/<batch-id>/export`.
