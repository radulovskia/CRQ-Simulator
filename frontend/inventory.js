const COLUMNS = [
  "Project",
  "PURL",
  "Business Process",
  "Organisational Unit",
  "Internet-facing?",
  "Criticality",
  "Potential Consequence",
];

const STORED_FIELDS = [
  "project",
  "purl",
  "business_process",
  "organisational_unit",
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
const totalCount = document.getElementById("total-count");
const sortButtons = [...document.querySelectorAll(".sort-button")];
const filterControls = [...document.querySelectorAll(".filter-row [data-field]")];

const CRITICALITY_RANK = { Low: 0, Medium: 1, High: 2 };

const storedPager = document.getElementById("stored-pager");

let storedItems = [];
let sortField = null;
let sortDirection = "asc";
let currentPage = 1;
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

function showTotalCount(count) {
  if (!count) {
    totalCount.hidden = true;
    totalCount.textContent = "";
    return;
  }
  totalCount.hidden = false;
  totalCount.textContent = `Total Count: ${count}`;
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

  currentPage = clampPage(visible.length, currentPage);

  if (!visible.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = STORED_FIELDS.length;
    cell.className = "empty-filter";
    cell.textContent = "No entries match these filters.";
    row.appendChild(cell);
    storedBody.replaceChildren(row);
    renderPager(storedPager, 0, 1, goToPage);
    return;
  }

  storedBody.replaceChildren(
    ...pageItems(visible, currentPage).map((item) => {
      const row = document.createElement("tr");
      STORED_FIELDS.forEach((field) => {
        const cell = document.createElement("td");
        cell.textContent = item[field] ?? "";
        row.appendChild(cell);
      });
      return row;
    }),
  );
  renderPager(storedPager, visible.length, currentPage, goToPage);
}

function goToPage(page) {
  currentPage = page;
  renderStoredRows();
}

function showStoredLayout() {
  reviewSection.hidden = true;
  const hasInventory = storedItems.length > 0;
  uploadPanel.hidden = hasInventory;
  replaceButton.hidden = !hasInventory;
  storedSection.hidden = !hasInventory;
  showTotalCount(hasInventory ? storedItems.length : 0);
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
  currentPage = 1;
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
  setStatus("Saving inventory and scanning for vulnerabilities…", "success");

  try {
    const body = new FormData();
    body.append("file", file);
    const response = await fetch("/inventory", { method: "POST", body });
    const data = await response.json();

    if (data.ok) {
      await loadInventory();
      const saved = `Saved ${data.count} ${data.count === 1 ? "entry" : "entries"}.`;
      if (data.scan_ok) {
        const found = data.vulnerability_count ?? 0;
        const scanMessage = found === 0
          ? "Vulnerability scan found no vulnerabilities."
          : `Vulnerability scan saved ${found} ${found === 1 ? "vulnerability" : "vulnerabilities"}.`;
        setStatus(`${saved} ${scanMessage}`, "success");
      } else {
        setStatus(`${saved} ${data.scan_error || "The vulnerability scan failed."}`, "error");
      }
      const missing = data.missing_business_processes ?? [];
      if (missing.length) {
        openMissingProcesses(missing);
      }
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

const missingModal = document.getElementById("missing-modal");
const missingForm = document.getElementById("missing-form");
const missingList = document.getElementById("missing-list");
const missingCancel = document.getElementById("missing-cancel");

function openMissingProcesses(names) {
  missingList.replaceChildren(
    ...names.map((name) => {
      const block = document.createElement("div");
      block.className = "missing-process";
      block.dataset.name = name;

      const title = document.createElement("p");
      title.className = "missing-process-name";
      title.textContent = name;
      block.appendChild(title);

      const unitLabel = document.createElement("label");
      unitLabel.className = "field";
      unitLabel.append("Organisational Unit");
      const unit = document.createElement("input");
      unit.type = "text";
      unit.autocomplete = "off";
      unitLabel.appendChild(unit);
      const unitError = document.createElement("span");
      unitError.className = "field-error";
      unitError.hidden = true;
      unitLabel.appendChild(unitError);
      block.appendChild(unitLabel);

      const criticalityLabel = document.createElement("label");
      criticalityLabel.className = "field";
      criticalityLabel.append("Criticality");
      const criticality = document.createElement("select");
      ["", "Low", "Medium", "High"].forEach((value) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value || "Select";
        criticality.appendChild(option);
      });
      criticalityLabel.appendChild(criticality);
      const criticalityError = document.createElement("span");
      criticalityError.className = "field-error";
      criticalityError.hidden = true;
      criticalityLabel.appendChild(criticalityError);
      block.appendChild(criticalityLabel);
      return block;
    }),
  );
  missingModal.hidden = false;
  missingList.querySelector("input")?.focus();
}

function closeMissingProcesses() {
  missingModal.hidden = true;
  missingList.replaceChildren();
}

async function saveMissingProcesses(event) {
  event.preventDefault();
  const blocks = [...missingList.querySelectorAll(".missing-process")];
  let valid = true;
  const entries = blocks.map((block) => {
    const unit = block.querySelector("input");
    const criticality = block.querySelector("select");
    const errors = block.querySelectorAll(".field-error");
    const unitError = errors[0];
    const criticalityError = errors[1];
    unitError.hidden = true;
    criticalityError.hidden = true;
    const organisationalUnit = unit.value.trim();
    if (!organisationalUnit) {
      unitError.hidden = false;
      unitError.textContent = "must not be empty";
      valid = false;
    }
    if (!["Low", "Medium", "High"].includes(criticality.value)) {
      criticalityError.hidden = false;
      criticalityError.textContent = 'must be "Low", "Medium", or "High"';
      valid = false;
    }
    return {
      business_process: block.dataset.name,
      organisational_unit: organisationalUnit,
      criticality: criticality.value,
    };
  });
  if (!valid) {
    return;
  }

  const saveButton = document.getElementById("missing-save");
  saveButton.disabled = true;
  try {
    const response = await fetch("/processes/entries", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entries }),
    });
    const data = await response.json();
    if (!data.ok) {
      setStatus(data.error || "The business processes could not be saved.", "error");
      return;
    }
    closeMissingProcesses();
    const count = data.count ?? entries.length;
    setStatus(`Added ${count} ${count === 1 ? "business process" : "business processes"}.`, "success");
  } catch (error) {
    setStatus(error.message || "The business processes could not be saved.", "error");
  } finally {
    saveButton.disabled = false;
  }
}

missingCancel.addEventListener("click", closeMissingProcesses);
missingForm.addEventListener("submit", saveMissingProcesses);
missingModal.addEventListener("click", (event) => {
  if (event.target === missingModal) {
    closeMissingProcesses();
  }
});

sortButtons.forEach((button) => {
  button.addEventListener("click", () => {
    if (sortField === button.dataset.field) {
      sortDirection = sortDirection === "asc" ? "desc" : "asc";
    } else {
      sortField = button.dataset.field;
      sortDirection = "asc";
    }
    currentPage = 1;
    renderStoredRows();
  });
});

filterControls.forEach((control) => {
  control.addEventListener("input", () => {
    filters[control.dataset.field] = control.value;
    currentPage = 1;
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
