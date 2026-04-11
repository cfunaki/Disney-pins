"use strict";

const state = {
  batchId: null,
  pins: [],
  selectedPinId: null,
  sortBy: "risk",
  filter: "",
};

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
      <img class="queue-thumb" src="${pinThumbnail(pin)}" alt="">
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
  container.innerHTML = `
    ${renderDetailHeader(pin)}
    <div class="detail-section" id="match-section">${renderMatchSection(pin)}</div>
    <div class="detail-section" id="extraction-section">${renderExtractionSection(pin)}</div>
    <div class="detail-section" id="draft-section"><!-- Task 15 --></div>
  `;
  _applyBackgrounds(container);
  wireMatchSection(pin);
  wireExtractionSection(pin);
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
      const id = parseInt(card.dataset.catalogEntryId, 10);
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

function wireExtractionSection(pin) {
  const container = document.getElementById("detail-content");
  const button = container.querySelector('[data-action="save-rematch"]');
  if (!button) return;
  button.addEventListener("click", async () => {
    const body = {};
    container.querySelectorAll("#extraction-section [data-field]").forEach((input) => {
      body[input.dataset.field] = input.value;
    });
    if (typeof body.characters === "string") {
      body.characters = body.characters.split(",").map((s) => s.trim()).filter((s) => s.length > 0);
    }
    if (body.edition_size === "" || body.edition_size == null) {
      body.edition_size = null;
    } else {
      const parsed = parseInt(body.edition_size, 10);
      body.edition_size = Number.isNaN(parsed) ? null : parsed;
    }
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

function escapeHtml(s) {
  if (s == null) return "";
  return String(s).replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
}

init();
