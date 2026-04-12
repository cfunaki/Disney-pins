"use strict";

const state = {
  batchId: null,
  pins: [],
  selectedPinId: null,
  sortBy: "risk",
  filter: "",
};

let catalogSearchOffset = 0;
let catalogSearchQuery = "";
let catalogModalPin = null;
let catalogSearchDebounceTimer = null;

const RISK_RANK = {
  no_match: 0,
  ambiguous_match: 1,
  low_extraction: 2,
  ready: 3,
  approved: 4,
  exported: 5,
};

const RISK_LABELS = {
  ready: { text: "✓ ready", cls: "badge-ready" },
  ambiguous_match: { text: "⚠ ambiguous match", cls: "badge-ambiguous" },
  low_extraction: { text: "⚠ low extraction", cls: "badge-low-extraction" },
  no_match: { text: "✗ no match", cls: "badge-no-match" },
  approved: { text: "✓ approved", cls: "badge-approved" },
  exported: { text: "→ exported", cls: "badge-exported" },
};

function init() {
  const root = document.getElementById("review-app");
  if (!root) return;
  state.batchId = root.dataset.batchId;
  document.getElementById("queue-filter").addEventListener("input", (e) => {
    state.filter = e.target.value.toLowerCase();
    renderQueueList();
  });
  document.getElementById("queue-sort").addEventListener("change", (e) => {
    state.sortBy = e.target.value;
    renderQueueList();
  });

  const modal = document.getElementById("catalog-modal");
  if (modal) {
    const closeBtn = modal.querySelector(".modal-close");
    if (closeBtn) closeBtn.addEventListener("click", closeCatalogSearchModal);
    const backdrop = modal.querySelector(".modal-backdrop");
    if (backdrop) backdrop.addEventListener("click", closeCatalogSearchModal);
    const input = modal.querySelector("#catalog-search-input");
    if (input) {
      input.addEventListener("input", (e) => {
        catalogSearchQuery = e.target.value;
        catalogSearchOffset = 0;
        if (catalogSearchDebounceTimer) clearTimeout(catalogSearchDebounceTimer);
        catalogSearchDebounceTimer = setTimeout(() => {
          runCatalogSearch(false);
        }, 250);
      });
    }
    const loadMoreBtn = modal.querySelector("#catalog-load-more");
    if (loadMoreBtn) {
      loadMoreBtn.addEventListener("click", () => {
        catalogSearchOffset += 20;
        runCatalogSearch(true);
      });
    }
  }

  document.addEventListener("keydown", (e) => {
    const modalOpen = modal && !modal.hidden;
    if (e.key === "Escape" && modalOpen) {
      e.preventDefault();
      closeCatalogSearchModal();
      return;
    }
    const tag = (e.target && e.target.tagName) || "";
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    if (modalOpen) return;

    const sorted = sortedFilteredPins();
    const idx = sorted.findIndex((p) => p.id === state.selectedPinId);

    if (e.key === "ArrowDown") {
      e.preventDefault();
      const next = sorted[Math.min(idx + 1, sorted.length - 1)];
      if (next) selectPin(next.id);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      const prev = sorted[Math.max(idx - 1, 0)];
      if (prev) selectPin(prev.id);
    } else if (e.key === "Enter") {
      e.preventDefault();
      const approveBtn = document.querySelector('.detail-actions [data-action="approve"]');
      if (approveBtn) approveBtn.click();
    }
  });

  loadBatch();
}

async function loadBatch() {
  try {
    const response = await fetch(`/api/batch/${state.batchId}/pins`);
    state.pins = await response.json();
    renderCounts();
    renderQueueList();
  } catch (err) {
    console.error("loadBatch failed:", err);
    document.getElementById("queue-list").innerHTML = '<li class="queue-error">Failed to load pins. Please refresh.</li>';
  }
}

function renderCounts() {
  const total = state.pins.length;
  const approved = state.pins.filter((p) => p.status === "approved" || p.status === "exported").length;
  document.getElementById("review-counts").textContent = `· ${total} pins · ${approved} approved`;
}

function pinTitle(pin) {
  if (pin.listing_draft && pin.listing_draft.title) return pin.listing_draft.title;
  const matches = pin.catalog_matches || [];
  if (matches.length > 0 && matches[0].canonical_name) return matches[0].canonical_name;
  return "(unknown)";
}

function _uploadsUrl(imagePath) {
  if (!imagePath) return "";
  const match = imagePath.match(/uploads\/(.+)$/);
  return match ? `/uploads/${match[1]}` : "";
}

function _sanitizeCssUrl(url) {
  if (!url) return "";
  if (/['"()\\\s<>]/.test(url)) return "";
  return url;
}

function _applyBackgrounds(container) {
  container.querySelectorAll("[data-bg]").forEach((el) => {
    const url = _sanitizeCssUrl(el.dataset.bg);
    if (url) el.style.backgroundImage = `url("${url}")`;
  });
}

function pinThumbnail(pin) {
  if (pin.image_paths && pin.image_paths.length > 0) {
    return _uploadsUrl(pin.image_paths[0]);
  }
  return "";
}

function sortedFilteredPins() {
  let pins = state.pins.slice();
  if (state.filter) {
    pins = pins.filter((p) => pinTitle(p).toLowerCase().includes(state.filter));
  }
  pins.sort((a, b) => {
    if (state.sortBy === "risk") {
      return (RISK_RANK[a.risk_badge] ?? 99) - (RISK_RANK[b.risk_badge] ?? 99);
    }
    if (state.sortBy === "price") {
      const pa = (a.listing_draft && a.listing_draft.suggested_price) || 0;
      const pb = (b.listing_draft && b.listing_draft.suggested_price) || 0;
      return pb - pa;
    }
    if (state.sortBy === "status") {
      return (a.status || "").localeCompare(b.status || "");
    }
    return a.id - b.id;
  });
  return pins;
}

function renderQueueList() {
  const list = document.getElementById("queue-list");
  list.innerHTML = "";
  for (const pin of sortedFilteredPins()) {
    const li = document.createElement("li");
    li.className = "queue-row" + (pin.id === state.selectedPinId ? " selected" : "");
    li.dataset.pinId = pin.id;
    const badge = RISK_LABELS[pin.risk_badge] || { text: pin.risk_badge || "—", cls: "" };
    const price = pin.listing_draft && pin.listing_draft.suggested_price
      ? `$${pin.listing_draft.suggested_price.toFixed(0)}` : "—";
    li.innerHTML = `
      <img class="queue-thumb" src="${escapeHtml(pinThumbnail(pin))}" alt="">
      <div class="queue-row-body">
        <div class="queue-title">${escapeHtml(pinTitle(pin))}</div>
        <div class="queue-meta">
          <span class="badge ${escapeHtml(badge.cls)}">${escapeHtml(badge.text)}</span>
          <span class="queue-price">${price}</span>
        </div>
      </div>`;
    li.addEventListener("click", () => selectPin(pin.id));
    list.appendChild(li);
    const img = li.querySelector("img.queue-thumb");
    if (img) img.addEventListener("error", () => { img.style.visibility = "hidden"; });
  }
}

async function selectPin(pinId) {
  state.selectedPinId = pinId;
  renderQueueList();
  document.getElementById("detail-empty").hidden = true;
  document.getElementById("detail-content").hidden = false;
  document.getElementById("detail-content").innerHTML = '<div class="loading">Loading…</div>';
  try {
    const response = await fetch(`/api/pins/${pinId}`);
    const pin = await response.json();
    const idx = state.pins.findIndex((p) => p.id === pin.id);
    if (idx >= 0) state.pins[idx] = pin;
    renderDetail(pin);
  } catch (err) {
    console.error("selectPin failed:", err);
    document.getElementById("detail-content").innerHTML = '<div class="detail-error">Failed to load pin details. Please try again.</div>';
  }
}

function renderDetail(pin) {
  const container = document.getElementById("detail-content");
  delete container.dataset.visualSelectedId;
  container.innerHTML = `
    ${renderDetailHeader(pin)}
    <div class="detail-section" id="match-section">${renderMatchSection(pin)}</div>
    <div class="detail-section" id="extraction-section">${renderExtractionSection(pin)}</div>
    <div class="detail-section" id="draft-section">${renderDraftSection(pin)}</div>
    ${renderReferenceLabel(pin)}
  `;
  _applyBackgrounds(container);
  wireMatchSection(pin);
  wireExtractionSection(pin);
  wireDraftSection(pin);
}

function renderDetailHeader(pin) {
  const badge = RISK_LABELS[pin.risk_badge] || { text: "", cls: "" };
  const title = pinTitle(pin);
  const reason = riskReason(pin);
  return `
    <div class="detail-header">
      <div>
        <div class="detail-title">Pin #${pin.id} · ${escapeHtml(title)}</div>
        <div class="detail-subtitle"><span class="badge ${escapeHtml(badge.cls)}">${escapeHtml(badge.text)}</span> ${escapeHtml(reason)}</div>
      </div>
      <div class="detail-actions">
        <button class="btn-approve" data-action="approve">Approve</button>
        <button class="btn-skip" data-action="skip">Skip</button>
      </div>
    </div>`;
}

function riskReason(pin) {
  if (pin.risk_badge === "ambiguous_match" && pin.catalog_matches && pin.catalog_matches.length >= 2) {
    const sorted = pin.catalog_matches.slice().sort((a, b) => b.match_confidence - a.match_confidence);
    const gap = (sorted[0].match_confidence - sorted[1].match_confidence).toFixed(2);
    return `Top two within ${gap}`;
  }
  if (pin.risk_badge === "low_extraction") {
    if (!pin.extraction || pin.extraction.confidence_score == null) return "";
    return `Vision confidence ${(pin.extraction.confidence_score * 100).toFixed(0)}%`;
  }
  if (pin.risk_badge === "no_match") {
    return pin.no_catalog_match ? "Marked no catalog match" : "Matcher returned no candidates";
  }
  return "";
}

function userPhoto(pin) {
  if (pin.image_paths && pin.image_paths.length > 0) {
    return _uploadsUrl(pin.image_paths[0]);
  }
  return "";
}

function catalogPhoto(match) {
  if (!match || !match.image_path) return "";
  return `/${match.image_path}`;
}

function renderMatchSection(pin) {
  const matches = (pin.catalog_matches || []).slice().sort((a, b) => b.match_confidence - a.match_confidence);
  const accepted = matches.find((m) => m.status === "accepted");
  const selected = accepted || matches[0] || null;

  if (matches.length === 0) {
    return `
      <div class="section-label">Section 1 · Match Review</div>
      <div class="empty-match">
        <p>No catalog candidates found for this pin.</p>
        <div class="match-actions">
          <button class="btn-danger" data-match-action="none">✗ Mark as no match</button>
          <button class="btn-neutral" data-match-action="search">🔍 Search catalog…</button>
        </div>
      </div>`;
  }

  const candidatesHtml = matches.map((m, i) => {
    const letter = String.fromCharCode(65 + i);
    const isSelected = selected && m.catalog_entry_id === selected.catalog_entry_id;
    const isAccepted = m.status === "accepted";
    return `
      <div class="candidate-card${isSelected ? " selected" : ""}${isAccepted ? " accepted" : ""}"
           data-catalog-entry-id="${m.catalog_entry_id}">
        <div class="candidate-image" data-bg="${escapeHtml(catalogPhoto(m))}">${letter} · ${m.match_confidence.toFixed(2)}${isAccepted ? " ✓" : ""}</div>
        <div class="candidate-name">${escapeHtml(m.canonical_name || "(no name)")}</div>
      </div>`;
  }).join("");

  const selectedHtml = selected ? `
    <div class="compare-pane">
      <div class="compare-label">Selected Catalog Match</div>
      <div class="compare-image" data-bg="${escapeHtml(catalogPhoto(selected))}"></div>
      <div class="compare-meta">
        <strong>${escapeHtml(selected.canonical_name || "")}</strong><br>
        <span class="muted">${escapeHtml(selected.source || "")} · ${selected.edition_size ? "LE " + escapeHtml(String(selected.edition_size)) : ""} · ${escapeHtml(String(selected.release_year || ""))}</span>
      </div>
    </div>` : "";

  return `
    <div class="section-label">Section 1 · Match Review</div>
    <div class="compare-row">
      <div class="compare-pane">
        <div class="compare-label">Your Photo</div>
        <div class="compare-image" data-bg="${escapeHtml(userPhoto(pin))}"></div>
      </div>
      ${selectedHtml}
    </div>
    <div class="match-actions">
      <button class="btn-success" data-match-action="accept">✓ Accept this match</button>
      <button class="btn-danger" data-match-action="none">✗ None of these</button>
      <button class="btn-neutral" data-match-action="search">🔍 Search catalog…</button>
    </div>
    <div class="section-label">Top ${matches.length} candidates · click to compare</div>
    <div class="candidate-strip">${candidatesHtml}</div>
  `;
}

function wireMatchSection(pin) {
  const container = document.getElementById("detail-content");
  container.querySelectorAll(".candidate-card").forEach((card) => {
    card.addEventListener("click", () => {
      const id = Number(card.dataset.catalogEntryId);
      if (!Number.isInteger(id)) return;
      container.querySelectorAll(".candidate-card").forEach((c) => c.classList.remove("selected"));
      card.classList.add("selected");
      const match = pin.catalog_matches.find((m) => m.catalog_entry_id === id);
      if (match) {
        const compareRow = container.querySelector(".compare-row");
        const compareCol = compareRow.querySelectorAll(".compare-pane")[1];
        if (compareCol) {
          const bgUrl = _sanitizeCssUrl(catalogPhoto(match));
          compareCol.querySelector(".compare-image").style.backgroundImage =
            bgUrl ? `url("${bgUrl}")` : "";
          compareCol.querySelector(".compare-meta").innerHTML =
            `<strong>${escapeHtml(match.canonical_name || "")}</strong><br>` +
            `<span class="muted">${escapeHtml(match.source || "")} · ${match.edition_size ? "LE " + escapeHtml(String(match.edition_size)) : ""} · ${escapeHtml(String(match.release_year || ""))}</span>`;
        }
      }
      container.dataset.visualSelectedId = id;
    });
  });

  const approveBtn = container.querySelector('[data-action="approve"]');
  if (approveBtn) {
    approveBtn.addEventListener("click", async () => {
      approveBtn.disabled = true;
      approveBtn.textContent = "Approving…";
      try {
        const extractionBody = collectExtractionFields(container);
        if (Object.keys(extractionBody).length > 0) {
          const extractionResp = await fetch(`/api/pins/${pin.id}/extraction`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(extractionBody),
          });
          if (!extractionResp.ok) {
            throw new Error(`Extraction save failed: ${extractionResp.status}`);
          }
        }
        const draftBody = collectDraftFields(container);
        const patchResp = await fetch(`/api/pins/${pin.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(draftBody),
        });
        if (!patchResp.ok) {
          throw new Error(`Draft save failed: ${patchResp.status}`);
        }
        const approveResp = await fetch(`/api/pins/${pin.id}/approve`, {
          method: "POST",
        });
        if (!approveResp.ok) {
          throw new Error(`Approve failed: ${approveResp.status}`);
        }
        const updated = await approveResp.json();
        replacePinInStateAndRender(updated);
      } catch (err) {
        console.error("approve failed:", err);
        container.querySelectorAll(".detail-error").forEach((el) => el.remove());
        const errorEl = document.createElement("div");
        errorEl.className = "detail-error";
        errorEl.textContent = "Approve failed. Please try again.";
        container.prepend(errorEl);
      } finally {
        approveBtn.disabled = false;
        approveBtn.textContent = "Approve";
      }
    });
  }

  const skipBtn = container.querySelector('[data-action="skip"]');
  if (skipBtn) {
    skipBtn.addEventListener("click", async () => {
      skipBtn.disabled = true;
      skipBtn.textContent = "Skipping…";
      try {
        const resp = await fetch(`/api/pins/${pin.id}/skip`, {
          method: "POST",
        });
        if (!resp.ok) {
          throw new Error(`Skip failed: ${resp.status}`);
        }
        const updated = await resp.json();
        replacePinInStateAndRender(updated);
        const sorted = sortedFilteredPins();
        const idx = sorted.findIndex((p) => p.id === pin.id);
        const next = sorted[idx + 1] || sorted[idx - 1];
        if (next && next.id !== pin.id) selectPin(next.id);
      } catch (err) {
        console.error("skip failed:", err);
        container.querySelectorAll(".detail-error").forEach((el) => el.remove());
        const errorEl = document.createElement("div");
        errorEl.className = "detail-error";
        errorEl.textContent = "Skip failed. Please try again.";
        container.prepend(errorEl);
      } finally {
        skipBtn.disabled = false;
        skipBtn.textContent = "Skip";
      }
    });
  }

  container.querySelectorAll(".match-actions [data-match-action]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const action = btn.dataset.matchAction;
      if (action === "search") {
        openCatalogSearchModal(pin);
        return;
      }
      btn.disabled = true;
      try {
        if (action === "accept") {
          let catalogEntryId = Number(container.dataset.visualSelectedId);
          if (!Number.isInteger(catalogEntryId)) {
            const matches = (pin.catalog_matches || []).slice().sort((a, b) => b.match_confidence - a.match_confidence);
            catalogEntryId = matches.length > 0 ? matches[0].catalog_entry_id : null;
          }
          const resp = await fetch(`/api/pins/${pin.id}/match/select`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ catalog_entry_id: catalogEntryId }),
          });
          if (!resp.ok) {
            throw new Error(`Accept failed: ${resp.status}`);
          }
          const updated = await resp.json();
          replacePinInStateAndRender(updated);
        } else if (action === "none") {
          const resp = await fetch(`/api/pins/${pin.id}/match/none`, {
            method: "POST",
          });
          if (!resp.ok) {
            throw new Error(`Mark no-match failed: ${resp.status}`);
          }
          const updated = await resp.json();
          replacePinInStateAndRender(updated);
        }
      } catch (err) {
        console.error(`match action ${action} failed:`, err);
        container.querySelectorAll(".detail-error").forEach((el) => el.remove());
        const errorEl = document.createElement("div");
        errorEl.className = "detail-error";
        errorEl.textContent = action === "accept" ? "Accept failed. Please try again." : "Mark no-match failed. Please try again.";
        container.prepend(errorEl);
      } finally {
        btn.disabled = false;
      }
    });
  });
}

function openCatalogSearchModal(pin) {
  const modal = document.getElementById("catalog-modal");
  if (!modal) return;
  catalogModalPin = pin;
  catalogSearchOffset = 0;
  catalogSearchQuery = "";
  const input = modal.querySelector("#catalog-search-input");
  if (input) input.value = "";
  const results = modal.querySelector("#catalog-results");
  if (results) results.innerHTML = "";
  const loadMoreBtn = modal.querySelector("#catalog-load-more");
  if (loadMoreBtn) loadMoreBtn.hidden = true;
  modal.querySelectorAll(".modal-error").forEach((el) => el.remove());
  modal.hidden = false;
  if (input) input.focus();
}

function closeCatalogSearchModal() {
  const modal = document.getElementById("catalog-modal");
  if (!modal) return;
  modal.hidden = true;
  catalogModalPin = null;
  catalogSearchQuery = "";
  catalogSearchOffset = 0;
  if (catalogSearchDebounceTimer) {
    clearTimeout(catalogSearchDebounceTimer);
    catalogSearchDebounceTimer = null;
  }
}

async function runCatalogSearch(append) {
  const modal = document.getElementById("catalog-modal");
  if (!modal) return;
  const results = modal.querySelector("#catalog-results");
  const loadMoreBtn = modal.querySelector("#catalog-load-more");
  if (!results) return;

  // Clear any previous modal errors on each attempt
  modal.querySelectorAll(".modal-error").forEach((el) => el.remove());

  const query = catalogSearchQuery.trim();
  if (!query) {
    results.innerHTML = "";
    if (loadMoreBtn) loadMoreBtn.hidden = true;
    return;
  }

  try {
    const url = `/api/catalog/search?q=${encodeURIComponent(query)}&offset=${catalogSearchOffset}`;
    const resp = await fetch(url);
    if (!resp.ok) {
      throw new Error(`Catalog search failed: ${resp.status}`);
    }
    const entries = await resp.json();

    if (!append) results.innerHTML = "";

    const fragment = document.createDocumentFragment();
    for (const e of entries) {
      const card = document.createElement("div");
      card.className = "catalog-result-card";
      const metaLine = [
        e.franchise || "",
        e.release_year != null ? String(e.release_year) : "",
        e.edition_size != null ? `LE ${e.edition_size}` : "",
      ].filter((s) => s && s.length > 0).join(" · ");
      const thumbPath = e.image_path ? `/${e.image_path}` : "";
      card.innerHTML = `
        <div class="catalog-thumb" data-bg="${escapeHtml(thumbPath)}"></div>
        <div class="catalog-result-body">
          <div class="catalog-result-name">${escapeHtml(e.canonical_name || "(no name)")}</div>
          <div class="catalog-result-meta muted">${escapeHtml(metaLine)}</div>
        </div>
        <button class="btn-primary catalog-use-btn" type="button" data-entry-id="${escapeHtml(String(e.id))}">Use this</button>
      `;
      fragment.appendChild(card);
    }
    results.appendChild(fragment);
    _applyBackgrounds(results);

    // Wire up "Use this" buttons for the newly added cards
    results.querySelectorAll(".catalog-use-btn").forEach((btn) => {
      if (btn.dataset.wired === "1") return;
      btn.dataset.wired = "1";
      btn.addEventListener("click", async () => {
        if (!catalogModalPin) return;
        // Re-read the target pin from state at click time so a queue click
        // that switches the selection while the modal is open can't cause
        // the match to be applied to the wrong pin.
        if (state.selectedPinId !== catalogModalPin.id) {
          closeCatalogSearchModal();
          return;
        }
        const entryId = Number(btn.dataset.entryId);
        if (!Number.isInteger(entryId)) return;
        btn.disabled = true;
        const originalText = btn.textContent;
        btn.textContent = "Selecting…";
        const pinId = catalogModalPin.id;
        try {
          const selectResp = await fetch(`/api/pins/${pinId}/match/select`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ catalog_entry_id: entryId }),
          });
          if (!selectResp.ok) {
            throw new Error(`Select failed: ${selectResp.status}`);
          }
          const updated = await selectResp.json();
          closeCatalogSearchModal();
          replacePinInStateAndRender(updated);
        } catch (err) {
          console.error("catalog use failed:", err);
          closeCatalogSearchModal();
          const detailContent = document.getElementById("detail-content");
          if (detailContent) {
            detailContent.querySelectorAll(".detail-error").forEach((el) => el.remove());
            const errorEl = document.createElement("div");
            errorEl.className = "detail-error";
            errorEl.textContent = "Catalog selection failed. Please try again.";
            detailContent.prepend(errorEl);
          }
        } finally {
          btn.disabled = false;
          btn.textContent = originalText;
        }
      });
    });

    if (loadMoreBtn) {
      loadMoreBtn.hidden = entries.length < 20;
    }
  } catch (err) {
    console.error("runCatalogSearch failed:", err);
    modal.querySelectorAll(".modal-error").forEach((el) => el.remove());
    const errorEl = document.createElement("div");
    errorEl.className = "modal-error";
    errorEl.textContent = "Catalog search failed. Please try again.";
    const body = modal.querySelector(".modal-body");
    if (body) body.prepend(errorEl);
  }
}

function renderExtractionSection(pin) {
  const e = pin.extraction || {};
  const characters = Array.isArray(e.characters) ? e.characters.join(", ") : (e.characters || "");
  const confidence = e.confidence_score != null
    ? `${(e.confidence_score * 100).toFixed(0)}%`
    : "—";
  return `
    <div class="section-label">Section 2 · Extraction</div>
    <div class="extraction-form">
      <div class="form-grid">
        <label>Characters
          <input type="text" data-field="characters" value="${escapeHtml(characters)}">
        </label>
        <label>Franchise
          <input type="text" data-field="franchise" value="${escapeHtml(e.franchise || "")}">
        </label>
        <label>Pin type
          <input type="text" data-field="pin_type" value="${escapeHtml(e.pin_type || "")}">
        </label>
        <label>Edition size
          <input type="number" data-field="edition_size" value="${escapeHtml(String(e.edition_size != null ? e.edition_size : ""))}">
        </label>
        <label>Visible dates
          <input type="text" data-field="visible_dates" value="${escapeHtml(e.visible_dates || "")}">
        </label>
        <label>Event clues
          <input type="text" data-field="event_clues" value="${escapeHtml(e.event_clues || "")}">
        </label>
      </div>
      <div class="extraction-footer">
        <span class="muted">Vision confidence: ${escapeHtml(String(confidence))}</span>
        <button class="btn-primary" data-action="save-rematch">💾 Save &amp; Re-match</button>
      </div>
    </div>
  `;
}

function collectExtractionFields(container) {
  const body = {};
  const section = container.querySelector("#extraction-section");
  if (!section) return body;
  section.querySelectorAll("[data-field]").forEach((input) => {
    body[input.dataset.field] = input.value;
  });
  if (typeof body.characters === "string") {
    body.characters = body.characters.split(",").map((s) => s.trim()).filter((s) => s.length > 0);
  }
  if (body.edition_size === "" || body.edition_size == null) {
    body.edition_size = null;
  } else {
    const parsed = Number(body.edition_size);
    body.edition_size = Number.isInteger(parsed) && parsed >= 0 ? parsed : null;
  }
  return body;
}

function wireExtractionSection(pin) {
  const container = document.getElementById("detail-content");
  const button = container.querySelector('[data-action="save-rematch"]');
  if (!button) return;
  button.addEventListener("click", async () => {
    const body = collectExtractionFields(container);
    button.disabled = true;
    button.textContent = "Saving + re-matching…";
    try {
      const extractionResp = await fetch(`/api/pins/${pin.id}/extraction`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!extractionResp.ok) {
        throw new Error(`Extraction save failed: ${extractionResp.status}`);
      }
      const rematchResp = await fetch(`/api/pins/${pin.id}/rematch`, {
        method: "POST",
      });
      if (!rematchResp.ok) {
        throw new Error(`Rematch failed: ${rematchResp.status}`);
      }
      const updated = await rematchResp.json();
      const idx = state.pins.findIndex((p) => p.id === updated.id);
      if (idx >= 0) state.pins[idx] = updated;
      renderQueueList();
      renderDetail(updated);
    } catch (err) {
      console.error("save-rematch failed:", err);
      const detailContent = document.getElementById("detail-content");
      detailContent.querySelectorAll(".detail-error").forEach((el) => el.remove());
      const errorEl = document.createElement("div");
      errorEl.className = "detail-error";
      errorEl.textContent = "Save failed. Please try again.";
      detailContent.prepend(errorEl);
    } finally {
      button.disabled = false;
      button.textContent = "💾 Save & Re-match";
    }
  });
}

function renderDraftSection(pin) {
  const d = pin.listing_draft || {};
  const matches = pin.catalog_matches || [];
  const accepted = matches.find((m) => m.status === "accepted");
  let banner = "";
  if (accepted) {
    banner = `<div class="draft-banner">↻ Draft will auto-regenerate from the accepted match when you click Regenerate.</div>`;
  } else if (pin.no_catalog_match) {
    banner = `<div class="draft-banner">⚠ Marked as no catalog match — edit freely below.</div>`;
  }
  const suggestedPriceVal = escapeHtml(String(d.suggested_price != null ? d.suggested_price : ""));
  const quickSalePriceVal = escapeHtml(String(d.quick_sale_price != null ? `$${d.quick_sale_price.toFixed(2)}` : "—"));
  const priceConfidenceVal = escapeHtml(String(d.price_confidence || "—"));
  const reasoningVal = escapeHtml(String(d.pricing_reasoning || ""));
  const tagsVal = escapeHtml((d.tags_keywords || []).join(", "));
  return `
    <div class="section-label">Section 3 · Listing Draft</div>
    ${banner}
    <div class="draft-form">
      <label>Title
        <input type="text" maxlength="80" data-draft-field="title" value="${escapeHtml(d.title || "")}">
      </label>
      <label>Description
        <textarea data-draft-field="description" rows="5">${escapeHtml(d.description || "")}</textarea>
      </label>
      <div class="form-grid form-grid-3">
        <label>Suggested price
          <input type="number" step="0.01" data-draft-field="suggested_price" value="${suggestedPriceVal}">
        </label>
        <label>Quick-sale price
          <span class="readonly-value">${quickSalePriceVal}</span>
        </label>
        <label>Price confidence
          <span class="readonly-value">${priceConfidenceVal}</span>
        </label>
      </div>
      ${reasoningVal ? `<div class="pricing-reasoning">💡 ${reasoningVal}</div>` : ""}
      <label>Tags / keywords
        <input type="text" data-draft-field="tags_keywords" value="${tagsVal}">
      </label>
      <div class="draft-footer">
        <button class="btn-neutral" data-action="regenerate">↻ Regenerate from match</button>
        <button class="btn-primary" data-action="save-draft">💾 Save draft</button>
      </div>
    </div>
  `;
}

function wireDraftSection(pin) {
  const container = document.getElementById("detail-content");
  const regenBtn = container.querySelector('[data-action="regenerate"]');
  const saveBtn = container.querySelector('[data-action="save-draft"]');

  if (regenBtn) {
    regenBtn.addEventListener("click", async () => {
      regenBtn.disabled = true;
      regenBtn.textContent = "Regenerating…";
      try {
        const resp = await fetch(`/api/pins/${pin.id}/draft/regenerate`, {
          method: "POST",
        });
        if (!resp.ok) {
          throw new Error(`Regenerate failed: ${resp.status}`);
        }
        const updated = await resp.json();
        replacePinInStateAndRender(updated);
      } catch (err) {
        console.error("regenerate failed:", err);
        const detailContent = document.getElementById("detail-content");
        detailContent.querySelectorAll(".detail-error").forEach((el) => el.remove());
        const errorEl = document.createElement("div");
        errorEl.className = "detail-error";
        errorEl.textContent = "Regenerate failed. Please try again.";
        detailContent.prepend(errorEl);
      } finally {
        regenBtn.disabled = false;
        regenBtn.textContent = "↻ Regenerate from match";
      }
    });
  }

  if (saveBtn) {
    saveBtn.addEventListener("click", async () => {
      const body = collectDraftFields(container);
      saveBtn.disabled = true;
      saveBtn.textContent = "Saving…";
      try {
        const resp = await fetch(`/api/pins/${pin.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!resp.ok) {
          throw new Error(`Draft save failed: ${resp.status}`);
        }
        const updated = await resp.json();
        replacePinInStateAndRender(updated);
      } catch (err) {
        console.error("save-draft failed:", err);
        const detailContent = document.getElementById("detail-content");
        detailContent.querySelectorAll(".detail-error").forEach((el) => el.remove());
        const errorEl = document.createElement("div");
        errorEl.className = "detail-error";
        errorEl.textContent = "Draft save failed. Please try again.";
        detailContent.prepend(errorEl);
      } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = "💾 Save draft";
      }
    });
  }
}

function collectDraftFields(container) {
  const body = {};
  container.querySelectorAll("#draft-section [data-draft-field]").forEach((inp) => {
    const field = inp.dataset.draftField;
    if (field === "tags_keywords") {
      body[field] = inp.value
        .split(",")
        .map((s) => s.trim())
        .filter((s) => s.length > 0);
    } else if (field === "suggested_price") {
      if (inp.value === "" || inp.value == null) {
        body[field] = null;
      } else {
        const parsed = Number(inp.value);
        body[field] = Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
      }
    } else {
      body[field] = inp.value || null;
    }
  });
  return body;
}

function replacePinInStateAndRender(pin) {
  const idx = state.pins.findIndex((p) => p.id === pin.id);
  if (idx >= 0) state.pins[idx] = pin;
  renderQueueList();
  renderCounts();
  renderDetail(pin);
}

function escapeHtml(s) {
  if (s == null) return "";
  return String(s).replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
}

// ── Reference label diff overlay ───────────────────────────────────
// Mirrors src/pipeline/reference_diff.py. Field list and comparator rules
// MUST stay in sync with that module.

const REFERENCE_GRADED_FIELDS = [
  "characters",
  "franchise",
  "canonical_name",
  "series_or_collection",
  "release_year",
  "edition_size",
  "is_limited_edition",
];

const REFERENCE_UNGRADED_FIELDS = [
  "event",
  "pin_type",
  "exclusive_source",
];

const REFERENCE_ALL_FIELDS = [
  ...REFERENCE_GRADED_FIELDS,
  ...REFERENCE_UNGRADED_FIELDS,
];

const REFERENCE_FIELD_LABELS = {
  characters: "Characters",
  franchise: "Franchise",
  canonical_name: "Canonical name",
  series_or_collection: "Series",
  release_year: "Year",
  edition_size: "Edition size",
  is_limited_edition: "LE flag",
  event: "Event",
  pin_type: "Pin type",
  exclusive_source: "Exclusive source",
};

function _refPresent(value) {
  if (value === null || value === undefined) return false;
  if (Array.isArray(value) && value.length === 0) return false;
  if (typeof value === "string" && value.trim() === "") return false;
  return true;
}

function _refNormList(value) {
  if (!Array.isArray(value)) return new Set();
  return new Set(
    value
      .map((v) => String(v).trim().toLowerCase())
      .filter((v) => v.length > 0),
  );
}

function _refSetsEqual(a, b) {
  if (a.size !== b.size) return false;
  for (const x of a) if (!b.has(x)) return false;
  return true;
}

function _refCompareField(field, tool, reference) {
  if (field === "characters") {
    return _refSetsEqual(_refNormList(tool), _refNormList(reference)) ? "agree" : "mismatch";
  }
  if (["franchise", "canonical_name", "series_or_collection", "event", "pin_type", "exclusive_source"].includes(field)) {
    const a = String(tool).trim().toLowerCase();
    const b = String(reference).trim().toLowerCase();
    if (a === b || a.includes(b) || b.includes(a)) return "agree";
    return "mismatch";
  }
  // release_year, edition_size, is_limited_edition
  return tool === reference ? "agree" : "mismatch";
}

function diffReferenceFields(tool, reference) {
  const out = {};
  for (const field of REFERENCE_ALL_FIELDS) {
    const t = tool[field];
    const r = reference[field];
    const tP = _refPresent(t);
    const rP = _refPresent(r);
    let status;
    if (!tP && !rP) {
      status = "muted";
    } else if (tP !== rP) {
      status = "one_side_only";
    } else {
      status = _refCompareField(field, t, r);
    }
    out[field] = { field, status, tool: t, reference: r };
  }
  return out;
}

function _flattenToolSide(pin) {
  const extraction = pin.extraction || {};
  const topMatch = (pin.catalog_matches || [])
    .slice()
    .sort((a, b) => b.match_confidence - a.match_confidence)[0];
  const entry = topMatch || {};
  return {
    characters: extraction.characters || [],
    franchise: extraction.franchise || null,
    canonical_name: pin.no_catalog_match ? null : (entry.canonical_name || null),
    series_or_collection: pin.no_catalog_match ? null : (entry.series_or_collection || null),
    release_year: pin.no_catalog_match ? null : (entry.release_year ?? null),
    edition_size: pin.no_catalog_match ? null : (entry.edition_size ?? null),
    is_limited_edition: extraction.edition_size != null ? true : null,
    event: null,
    pin_type: extraction.pin_type || null,
    exclusive_source: null,
  };
}

function _formatRefValue(value) {
  if (value === null || value === undefined) return "—";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "boolean") return value ? "yes" : "no";
  return String(value);
}

const _REF_STATUS_ICON = {
  agree: "✓",
  mismatch: "✗",
  one_side_only: "⚠",
  muted: "·",
};

const _REF_STATUS_CLASS = {
  agree: "agree",
  mismatch: "mismatch",
  one_side_only: "one-side",
  muted: "muted",
};

function renderReferenceLabel(pin) {
  if (!pin.reference_source) return "";

  const parsed = pin.reference_parsed_fields || {};
  const tool = _flattenToolSide(pin);
  const diff = diffReferenceFields(tool, parsed);

  const hasMismatch = Object.values(diff).some((d) => d.status === "mismatch");
  const openAttr = hasMismatch ? " open" : "";
  const rawTitle = pin.reference_raw_title || "";
  const ebayLink = pin.reference_url
    ? `<a class="ref-ebay-link" href="${escapeHtml(pin.reference_url)}" target="_blank" rel="noopener">↗ eBay</a>`
    : "";

  const rows = REFERENCE_ALL_FIELDS.map((field) => {
    const d = diff[field];
    const cls = `diff-row diff-${_REF_STATUS_CLASS[d.status]}`;
    const icon = _REF_STATUS_ICON[d.status];
    return `
      <tr class="${cls}">
        <th>${escapeHtml(REFERENCE_FIELD_LABELS[field])}</th>
        <td>${escapeHtml(_formatRefValue(d.reference))}</td>
        <td><span class="diff-status diff-${_REF_STATUS_CLASS[d.status]}">${icon}</span>${escapeHtml(_formatRefValue(d.tool))}</td>
      </tr>`;
  }).join("");

  return `
    <details class="reference-section"${openAttr}>
      <summary>
        <span>Reference label (${escapeHtml(pin.reference_source)})</span>
        ${ebayLink}
      </summary>
      <div class="reference-raw-title">"${escapeHtml(rawTitle)}"</div>
      <table class="reference-diff-table">
        <thead>
          <tr><th></th><th>Parsed reference</th><th>Tool extraction</th></tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </details>`;
}

init();
