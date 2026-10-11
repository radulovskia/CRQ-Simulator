const COLUMNS = [
  "PURL",
  "Business Purpose",
  "Internet-facing?",
  "Criticality",
  "Potential consequence",
];

const STORED_FIELDS = [
  "purl",
  "business_purpose",
  "internet_facing",
  "criticality",
  "potential_consequence",
];

const uploadPanel = document.getElementById("upload-panel");
const dropzone = document.getElementById("dropzone");
const uploadButton = document.getElementById("upload-button");
const replaceButton = document.getElementById("replace-button");
const fileInput = document.getElementById("file-input");
const statusBox = document.getElementById("status");
const reviewSection = document.getElementById("review");
const reviewHead = document.getElementById("review-head");
const reviewBody = document.getElementById("review-body");
const storedSection = document.getElementById("stored");
const storedBody = document.getElementById("stored-body");
const inventoryCount = document.getElementById("inventory-count");
const lastExtraction = document.getElementById("last-extraction");
const sortButtons = [...document.querySelectorAll(".sort-button")];
const filterControls = [...document.querySelectorAll(".filter-row [data-field]")];

const CRITICALITY_RANK = { Low: 0, Medium: 1, High: 2 };

let storedItems = [];
let sortField = null;
let sortDirection = "asc";
const filters = Object.fromEntries(STORED_FIELDS.map((field) => [field, ""]));

function setStatus(message, type) {
  statusBox.hidden = false;
  statusBox.textContent = message;
  statusBox.className = `status ${type}`;
}

function clearStatus() {
  statusBox.hidden = true;
  statusBox.textContent = "";
  statusBox.className = "status";
}

function showLastExtraction(extractedAt) {
  const parsed = extractedAt ? new Date(extractedAt) : null;
  if (!parsed || Number.isNaN(parsed.getTime())) {
    lastExtraction.hidden = true;
    lastExtraction.textContent = "";
    return;
  }
  lastExtraction.hidden = false;
  lastExtraction.textContent = `Last extraction: ${parsed.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  })}`;
}

function compareValues(field, left, right) {
  if (field === "criticality") {
    return (CRITICALITY_RANK[left] ?? 99) - (CRITICALITY_RANK[right] ?? 99);
  }
  return String(left).localeCompare(String(right), undefined, { numeric: true, sensitivity: "base" });
}

function visibleItems() {
  const matched = storedItems.filter((item) =>
    STORED_FIELDS.every((field) => {
      const query = filters[field].trim();
      if (!query) {
        return true;
      }
      const value = String(item[field] ?? "");
      const control = filterControls.find((element) => element.dataset.field === field);
      if (control?.tagName === "SELECT") {
        return value === query;
      }
      return value.toLocaleLowerCase().includes(query.toLocaleLowerCase());
    }),
  );

  if (!sortField) {
    return matched;
  }
  const direction = sortDirection === "desc" ? -1 : 1;
  return matched.slice().sort((left, right) => direction * compareValues(sortField, left[sortField], right[sortField]));
}

function updateSortIndicators() {
  sortButtons.forEach((button) => {
    const active = button.dataset.field === sortField;
    button.closest("th").setAttribute("aria-sort", active ? (sortDirection === "asc" ? "ascending" : "descending") : "none");
    button.querySelector(".sort-indicator").textContent = active ? (sortDirection === "asc" ? "▲" : "▼") : "";
  });
}

function renderStoredRows() {
  updateSortIndicators();
  const visible = visibleItems();
  const filtered = visible.length !== storedItems.length;
  inventoryCount.hidden = !filtered;
  inventoryCount.textContent = filtered ? `Showing ${visible.length} of ${storedItems.length}` : "";

  if (!visible.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = STORED_FIELDS.length;
    cell.className = "empty-filter";
    cell.textContent = "No entries match these filters.";
    row.appendChild(cell);
    storedBody.replaceChildren(row);
    return;
  }

  storedBody.replaceChildren(
    ...visible.map((item) => {
      const row = document.createElement("tr");
      STORED_FIELDS.forEach((field) => {
        const cell = document.createElement("td");
        cell.textContent = item[field];
        row.appendChild(cell);
      });
      return row;
    }),
  );
}

function showStoredLayout() {
  reviewSection.hidden = true;
  const hasInventory = storedItems.length > 0;
  uploadPanel.hidden = hasInventory;
  replaceButton.hidden = !hasInventory;
  storedSection.hidden = !hasInventory;
  if (hasInventory) {
    renderStoredRows();
  }
}

function showReview(rows) {
  reviewHead.replaceChildren();
  const headRow = document.createElement("tr");
  ["Row", ...COLUMNS].forEach((label) => {
    const cell = document.createElement("th");
    cell.textContent = label;
    headRow.appendChild(cell);
  });
  reviewHead.appendChild(headRow);

  reviewBody.replaceChildren(
    ...rows.map((entry) => {
      const row = document.createElement("tr");
      const numberCell = document.createElement("td");
      numberCell.textContent = String(entry.row);
      row.appendChild(numberCell);

      COLUMNS.forEach((column) => {
        const cell = document.createElement("td");
        const value = document.createElement("span");
        value.textContent = entry.values[column] ?? "";
        cell.appendChild(value);
        const reason = entry.errors?.[column];
        if (reason) {
          cell.className = "cell-invalid";
          const note = document.createElement("span");
          note.className = "cell-reason";
          note.textContent = reason;
          cell.appendChild(note);
        }
        row.appendChild(cell);
      });
      return row;
    }),
  );

  const hasInventory = storedItems.length > 0;
  uploadPanel.hidden = hasInventory;
  replaceButton.hidden = !hasInventory;
  storedSection.hidden = true;
  reviewSection.hidden = false;
}

async function loadInventory() {
  const response = await fetch("/inventory");
  if (!response.ok) {
    throw new Error("The inventory could not be loaded.");
  }
  const data = await response.json();
  storedItems = data.items ?? [];
  showLastExtraction(data.extracted_at);
  clearStatus();
  showStoredLayout();
}

async function uploadFile(file) {
  const extension = file.name.split(".").pop()?.toLowerCase();
  if (extension !== "csv" && extension !== "xlsx") {
    setStatus("Upload a .csv or .xlsx file.", "error");
    return;
  }

  uploadButton.disabled = true;
  replaceButton.disabled = true;
  setStatus("Checking the file…", "success");

  try {
    const body = new FormData();
    body.append("file", file);
    const response = await fetch("/inventory", { method: "POST", body });
    const data = await response.json();

    if (data.ok) {
      await loadInventory();
      setStatus(`Saved ${data.count} ${data.count === 1 ? "entry" : "entries"}.`, "success");
      return;
    }

    if (data.rows) {
      const failing = data.rows.filter((entry) => Object.keys(entry.errors ?? {}).length > 0).length;
      setStatus(
        `${failing} ${failing === 1 ? "entry does" : "entries do"} not comply. Nothing was saved.`,
        "error",
      );
      showReview(data.rows);
      return;
    }

    showStoredLayout();
    setStatus(data.error || "The file could not be saved.", "error");
  } catch (error) {
    setStatus(error.message || "The file could not be uploaded.", "error");
  } finally {
    uploadButton.disabled = false;
    replaceButton.disabled = false;
    fileInput.value = "";
  }
}

sortButtons.forEach((button) => {
  button.addEventListener("click", () => {
    if (sortField === button.dataset.field) {
      sortDirection = sortDirection === "asc" ? "desc" : "asc";
    } else {
      sortField = button.dataset.field;
      sortDirection = "asc";
    }
    renderStoredRows();
  });
});

filterControls.forEach((control) => {
  control.addEventListener("input", () => {
    filters[control.dataset.field] = control.value;
    renderStoredRows();
  });
});

uploadButton.addEventListener("click", () => fileInput.click());
replaceButton.addEventListener("click", () => fileInput.click());

fileInput.addEventListener("change", () => {
  const file = fileInput.files?.[0];
  if (file) {
    uploadFile(file);
  }
});

["dragenter", "dragover"].forEach((eventName) => {
  dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropzone.classList.add("dragover");
  });
});

["dragleave", "drop"].forEach((eventName) => {
  dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropzone.classList.remove("dragover");
  });
});

dropzone.addEventListener("drop", (event) => {
  const file = event.dataTransfer?.files?.[0];
  if (file) {
    uploadFile(file);
  }
});

loadInventory().catch((error) => {
  setStatus(error.message || "The inventory could not be loaded.", "error");
});
