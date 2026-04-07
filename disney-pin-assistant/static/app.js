const dropZone = document.getElementById("drop-zone");
const fileInput = document.getElementById("file-input");
const fileList = document.getElementById("file-list");
const uploadForm = document.getElementById("upload-form");
const uploadBtn = document.getElementById("upload-btn");

if (dropZone) {
    dropZone.addEventListener("click", () => fileInput.click());
    dropZone.addEventListener("dragover", (e) => { e.preventDefault(); dropZone.classList.add("dragover"); });
    dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
    dropZone.addEventListener("drop", (e) => { e.preventDefault(); dropZone.classList.remove("dragover"); fileInput.files = e.dataTransfer.files; updateFileList(); });
    fileInput.addEventListener("change", updateFileList);
    uploadForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const formData = new FormData();
        for (const file of fileInput.files) { formData.append("files", file); }
        const photoType = document.getElementById("photo-type").value;
        if (photoType) { formData.append("photo_type", photoType); }
        uploadBtn.disabled = true;
        uploadBtn.textContent = "Uploading...";
        const response = await fetch("/api/upload", { method: "POST", body: formData });
        const data = await response.json();
        await fetch(`/api/batch/${data.batch_id}/process`, { method: "POST" });
        document.getElementById("progress-container").hidden = false;
        document.getElementById("batch-id").textContent = data.batch_id;
        document.getElementById("total-count").textContent = data.pins.length;
        pollProgress(data.batch_id, data.pins.length);
    });
}

function updateFileList() {
    const files = fileInput.files;
    fileList.textContent = `${files.length} file(s) selected`;
    uploadBtn.disabled = files.length === 0;
}

async function pollProgress(batchId, total) {
    const interval = setInterval(async () => {
        const response = await fetch(`/api/batch/${batchId}/progress`);
        const data = await response.json();
        document.getElementById("processed-count").textContent = data.processed;
        const pct = Math.round((data.processed / total) * 100);
        document.getElementById("progress-fill").style.width = `${pct}%`;
        if (data.processed >= total) {
            clearInterval(interval);
            const link = document.getElementById("review-link");
            link.href = `/queue/${batchId}`;
            link.hidden = false;
        }
    }, 2000);
}

async function approvePin(pinId) { await fetch(`/api/pins/${pinId}/approve`, { method: "POST" }); location.reload(); }
async function skipPin(pinId) { await fetch(`/api/pins/${pinId}/skip`, { method: "POST" }); location.reload(); }

async function approveAllHighConfidence(batchId) {
    const response = await fetch(`/api/batch/${batchId}/pins`);
    const pins = await response.json();
    for (const pin of pins) {
        if (pin.extraction && pin.extraction.confidence_score >= 0.8 && pin.status === "priced") {
            await fetch(`/api/pins/${pin.id}/approve`, { method: "POST" });
        }
    }
    location.reload();
}

async function savePin(pinId) {
    const title = document.getElementById("edit-title").value;
    const description = document.getElementById("edit-description").value;
    const price = parseFloat(document.getElementById("edit-price").value);
    await fetch(`/api/pins/${pinId}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, description, suggested_price: price }),
    });
    alert("Saved!");
}
