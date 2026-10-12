const COLUMNS = ["Business Process", "Organisational Unit", "Criticality"];

const STORED_FIELDS = ["business_process", "organisational_unit", "criticality", "date_added"];

const FIELD_ERRORS = {
  business_process: "error-business-process",
  organisational_unit: "error-organisational-unit",
  criticality: "error-criticality",
};

const ERROR_KEYS = {
  "Business Process": "business_process",
  "Organisational Unit": "organisational_unit",
  Criticality: "criticality",
};

const uploadPanel = document.getElementById("upload-panel");
const dropzone = document.getElementById("dropzone");
const uploadButton = document.getElementById("upload-button");
const replaceButton = document.getElementById("replace-button");
const addButton = document.getElementById("add-button");
const fileInput = document.getElementById("file-input");
const statusBox = document.getElementById("status");
const reviewSection = document.getElementById("review");
const reviewHead = document.getElementById("review-head");
const reviewBody = document.getElementById("review-body");
const storedSection = document.getElementById("stored");
const storedBody = document.getElementById("stored-body");
const catalogCount = document.getElementById("catalog-count");
const lastExtraction = document.getElementById("last-extraction");
const totalCount = document.getElementById("total-count");
const storedPager = document.getElementById("stored-pager");
const sortButtons = [...document.querySelectorAll(".sort-button")];
const filterControls = [...document.querySelectorAll(".filter-row [data-field]")];
const processModal = document.getElementById("process-modal");
const processForm = document.getElementById("process-form");
const processFormTitle = document.getElementById("process-form-title");
const processCancel = document.getElementById("process-cancel");
const missingNotice = document.getElementById("missing-notice");
const addMissingButton = document.getElementById("add-missing");
const missingModal = document.getElementById("missing-modal");
const missingForm = document.getElementById("missing-form");
const missingList = document.getElementById("missing-list");
const missingCancel = document.getElementById("missing-cancel");

const CRITICALITY_RANK = { Low: 0, Medium: 1, High: 2 };
const timestampFormat = {
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
};

let storedItems = [];
let missingNames = [];
let sortField = null;
let sortDirection = "asc";
let currentPage = 1;
let editingId = null;
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

function formatTimestamp(value) {
  const parsed = value ? new Date(value) : null;
  if (!parsed || Number.isNaN(parsed.getTime())) {
    return "";
  }
  return parsed.toLocaleString(undefined, timestampFormat);
}

function showLastExtraction(extractedAt) {
  const formatted = formatTimestamp(extractedAt);
  if (!formatted) {
    lastExtraction.hidden = true;
    lastExtraction.textContent = "";
    return;
  }
  lastExtraction.hidden = false;
  lastExtraction.textContent = `Last extraction: ${formatted}`;
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

function displayValue(item, field) {
  if (field === "date_added") {
    return formatTimestamp(item.date_added);
  }
  return item[field] ?? "";
}

function compareValues(field, left, right) {
  if (field === "criticality") {
    return (CRITICALITY_RANK[left.criticality] ?? 99) - (CRITICALITY_RANK[right.criticality] ?? 99);
  }
  if (field === "date_added") {
    return new Date(left.date_added).getTime() - new Date(right.date_added).getTime();
  }
  return String(left[field] ?? "").localeCompare(String(right[field] ?? ""), undefined, {
    numeric: true,
    sensitivity: "base",
  });
}

function visibleItems() {
  const matched = storedItems.filter((item) =>
    STORED_FIELDS.every((field) => {
      const query = filters[field].trim();
      if (!query) {
        return true;
      }
      const value = displayValue(item, field);
      const control = filterControls.find((element) => element.dataset.field === field);
      if (control?.tagName === "SELECT") {
        return item[field] === query;
      }
      return value.toLocaleLowerCase().includes(query.toLocaleLowerCase());
    }),
  );
  if (!sortField) {
    return matched;
  }
  const direction = sortDirection === "desc" ? -1 : 1;
  return matched.slice().sort((left, right) => direction * compareValues(sortField, left, right));
}

function updateSortIndicators() {
  sortButtons.forEach((button) => {
    const active = button.dataset.field === sortField;
    button.closest("th").setAttribute("aria-sort", active ? (sortDirection === "asc" ? "ascending" : "descending") : "none");
    button.querySelector(".sort-indicator").textContent = active ? (sortDirection === "asc" ? "▲" : "▼") : "";
  });
}

function pencilIcon() {
  const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  icon.setAttribute("viewBox", "0 0 24 24");
  icon.setAttribute("aria-hidden", "true");
  icon.classList.add("pencil-icon");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("fill", "currentColor");
  path.setAttribute(
    "d",
    "M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z",
  );
  icon.appendChild(path);
  return icon;
}

function renderStoredRows() {
  updateSortIndicators();
  const visible = visibleItems();
  const filtered = visible.length !== storedItems.length;
  catalogCount.hidden = !filtered;
  catalogCount.textContent = filtered ? `Showing ${visible.length} of ${storedItems.length}` : "";
  currentPage = clampPage(visible.length, currentPage);

  if (!visible.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 5;
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
        cell.textContent = displayValue(item, field);
        row.appendChild(cell);
      });
      const editCell = document.createElement("td");
      editCell.className = "edit-cell";
      const editButton = document.createElement("button");
      editButton.type = "button";
      editButton.className = "icon-button";
      editButton.setAttribute("aria-label", "Edit");
      editButton.appendChild(pencilIcon());
      editButton.addEventListener("click", () => openForm(item));
      editCell.appendChild(editButton);
      row.appendChild(editCell);
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
  const hasCatalog = storedItems.length > 0;
  uploadPanel.hidden = hasCatalog;
  replaceButton.hidden = !hasCatalog;
  storedSection.hidden = !hasCatalog;
  showTotalCount(hasCatalog ? storedItems.length : 0);
  if (hasCatalog) {
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

  const hasCatalog = storedItems.length > 0;
  uploadPanel.hidden = hasCatalog;
  replaceButton.hidden = !hasCatalog;
  storedSection.hidden = true;
  reviewSection.hidden = false;
}

function clearFormErrors() {
  Object.values(FIELD_ERRORS).forEach((id) => {
    const error = document.getElementById(id);
    error.hidden = true;
    error.textContent = "";
  });
}

function showFormErrors(errors) {
  clearFormErrors();
  Object.entries(errors).forEach(([key, message]) => {
    const field = ERROR_KEYS[key] || key;
    const error = document.getElementById(FIELD_ERRORS[field]);
    if (!error) {
      return;
    }
    error.hidden = false;
    error.textContent = message;
  });
}

function formValues() {
  return {
    business_process: document.getElementById("field-business-process").value.trim(),
    organisational_unit: document.getElementById("field-organisational-unit").value.trim(),
    criticality: document.getElementById("field-criticality").value,
  };
}

function clientErrors(values) {
  const errors = {};
  if (!values.business_process) {
    errors["Business Process"] = "must not be empty";
  }
  if (!values.organisational_unit) {
    errors["Organisational Unit"] = "must not be empty";
  }
  if (!["Low", "Medium", "High"].includes(values.criticality)) {
    errors.Criticality = 'must be "Low", "Medium", or "High"';
  }
  return errors;
}

function openForm(item) {
  editingId = item?.id ?? null;
  processFormTitle.textContent = editingId ? "Edit business process" : "Add business process";
  document.getElementById("field-business-process").value = item?.business_process ?? "";
  document.getElementById("field-organisational-unit").value = item?.organisational_unit ?? "";
  document.getElementById("field-criticality").value = item?.criticality ?? "";
  clearFormErrors();
  processModal.hidden = false;
  document.getElementById("field-business-process").focus();
}

function closeForm() {
  processModal.hidden = true;
  editingId = null;
}

async function loadCatalog() {
  const response = await fetch("/processes");
  if (!response.ok) {
    throw new Error("The business process catalog could not be loaded.");
  }
  const data = await response.json();
  storedItems = data.items ?? [];
  currentPage = 1;
  showLastExtraction(data.extracted_at);
  clearStatus();
  showStoredLayout();
  if (!storedItems.length) {
    await loadMissingNotice();
  }
}

async function loadMissingNotice() {
  const response = await fetch("/processes/missing");
  if (!response.ok) {
    throw new Error("The business processes from the Asset Inventory could not be loaded.");
  }
  const data = await response.json();
  missingNames = data.names ?? [];
  missingNotice.hidden = missingNames.length === 0;
}

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
    storedItems = data.items ?? [];
    currentPage = 1;
    showLastExtraction(data.extracted_at);
    showStoredLayout();
    const count = data.count ?? entries.length;
    setStatus(`Added ${count} ${count === 1 ? "business process" : "business processes"}.`, "success");
  } catch (error) {
    setStatus(error.message || "The business processes could not be saved.", "error");
  } finally {
    saveButton.disabled = false;
  }
}

async function saveForm(event) {
  event.preventDefault();
  const values = formValues();
  const errors = clientErrors(values);
  if (Object.keys(errors).length) {
    showFormErrors(errors);
    return;
  }

  const saveButton = document.getElementById("process-save");
  saveButton.disabled = true;
  try {
    const response = await fetch("/processes/entry", {
      method: editingId ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(editingId ? { id: editingId, ...values } : values),
    });
    const data = await response.json();
    if (!data.ok) {
      showFormErrors(data.errors || {});
      if (data.error) {
        setStatus(data.error, "error");
      }
      return;
    }
    const wasEdit = editingId != null;
    storedItems = data.items ?? [];
    showLastExtraction(data.extracted_at);
    closeForm();
    showStoredLayout();
    setStatus(wasEdit ? "Business process updated." : "Business process added.", "success");
  } catch (error) {
    setStatus(error.message || "The business process could not be saved.", "error");
  } finally {
    saveButton.disabled = false;
  }
}

async function uploadFile(file) {
  const extension = file.name.split(".").pop()?.toLowerCase();
  if (extension !== "csv" && extension !== "xlsx") {
    setStatus("Upload a .csv or .xlsx file.", "error");
    return;
  }

  uploadButton.disabled = true;
  replaceButton.disabled = true;
  setStatus("Saving the business process catalog…", "success");

  try {
    const body = new FormData();
    body.append("file", file);
    const response = await fetch("/processes", { method: "POST", body });
    const data = await response.json();

    if (data.ok) {
      storedItems = data.items ?? [];
      currentPage = 1;
      showLastExtraction(data.extracted_at);
      showStoredLayout();
      const count = data.count ?? storedItems.length;
      setStatus(`Saved ${count} ${count === 1 ? "entry" : "entries"}.`, "success");
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
addButton.addEventListener("click", () => openForm(null));
addMissingButton.addEventListener("click", () => openMissingProcesses(missingNames));
processCancel.addEventListener("click", closeForm);
processForm.addEventListener("submit", saveForm);
processModal.addEventListener("click", (event) => {
  if (event.target === processModal) {
    closeForm();
  }
});
missingCancel.addEventListener("click", closeMissingProcesses);
missingForm.addEventListener("submit", saveMissingProcesses);
missingModal.addEventListener("click", (event) => {
  if (event.target === missingModal) {
    closeMissingProcesses();
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") {
    return;
  }
  if (!processModal.hidden) {
    closeForm();
  }
  if (!missingModal.hidden) {
    closeMissingProcesses();
  }
});

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

loadCatalog().catch((error) => {
  setStatus(error.message || "The business process catalog could not be loaded.", "error");
});
