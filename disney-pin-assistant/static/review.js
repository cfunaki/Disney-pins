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
  const response = await fetch(`/api/batch/${state.batchId}/pins`);
  state.pins = await response.json();
  renderCounts();
  renderQueueList();
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

function pinThumbnail(pin) {
  if (pin.image_paths && pin.image_paths.length > 0) {
    return `/uploads/${pin.image_paths[0].replace(/^.*uploads\//, "")}`;
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
      <img class="queue-thumb" src="${pinThumbnail(pin)}" alt="" onerror="this.style.visibility='hidden'">
      <div class="queue-row-body">
        <div class="queue-title">${escapeHtml(pinTitle(pin))}</div>
        <div class="queue-meta">
          <span class="badge ${badge.cls}">${badge.text}</span>
          <span class="queue-price">${price}</span>
        </div>
      </div>`;
    li.addEventListener("click", () => selectPin(pin.id));
    list.appendChild(li);
  }
}

async function selectPin(pinId) {
  state.selectedPinId = pinId;
  renderQueueList();
  // Detail rendering added in Task 13
  document.getElementById("detail-empty").hidden = true;
  document.getElementById("detail-content").hidden = false;
  document.getElementById("detail-content").textContent = `Loading pin ${pinId}…`;
}

function escapeHtml(s) {
  if (s == null) return "";
  return String(s).replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
}

init();
