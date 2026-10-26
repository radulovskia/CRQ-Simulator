function mountCatalog(config) {
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
  const timestampFormat = { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" };

  let storedItems = [];
  let sortField = null;
  let sortDirection = "asc";
  let currentPage = 1;
  const filters = Object.fromEntries(config.fields.map((field) => [field.key, ""]));

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
    lastExtraction.hidden = !formatted;
    lastExtraction.textContent = formatted ? `Last extraction: ${formatted}` : "";
  }

  function showTotalCount(count) {
    totalCount.hidden = !count;
    totalCount.textContent = count ? `Total Count: ${count}` : "";
  }

  function displayValue(item, field) {
    return item[field] ?? "";
  }

  function compareValues(field, left, right) {
    const rank = config.ranks?.[field];
    if (rank) {
      return (rank[left[field]] ?? 99) - (rank[right[field]] ?? 99);
    }
    return String(left[field] ?? "").localeCompare(String(right[field] ?? ""), undefined, {
      numeric: true,
      sensitivity: "base",
    });
  }

  function visibleItems() {
    const matched = storedItems.filter((item) =>
      config.fields.every((field) => {
        const query = filters[field.key].trim();
        if (!query) {
          return true;
        }
        const control = filterControls.find((element) => element.dataset.field === field.key);
        if (control?.tagName === "SELECT") {
          return item[field.key] === query;
        }
        return String(displayValue(item, field.key)).toLocaleLowerCase().includes(query.toLocaleLowerCase());
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
      cell.colSpan = config.fields.length + 1;
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
        config.fields.forEach((field) => {
          const cell = document.createElement("td");
          cell.textContent = displayValue(item, field.key);
          row.appendChild(cell);
        });
        const editCell = document.createElement("td");
        editCell.className = "edit-cell";
        const editButton = document.createElement("button");
        editButton.type = "button";
        editButton.className = "icon-button";
        editButton.setAttribute("aria-label", "Edit");
        editButton.appendChild(pencilIcon());
        editButton.addEventListener("click", () => config.onEdit(item));
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
    const hasRows = storedItems.length > 0;
    uploadPanel.hidden = hasRows;
    replaceButton.hidden = !hasRows;
    storedSection.hidden = !hasRows;
    showTotalCount(hasRows ? storedItems.length : 0);
    if (hasRows) {
      renderStoredRows();
    }
  }

  function showReview(rows) {
    reviewHead.replaceChildren();
    const headRow = document.createElement("tr");
    ["Row", ...config.reviewColumns].forEach((label) => {
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
        config.reviewColumns.forEach((column) => {
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
    const hasRows = storedItems.length > 0;
    uploadPanel.hidden = hasRows;
    replaceButton.hidden = !hasRows;
    storedSection.hidden = true;
    reviewSection.hidden = false;
  }

  function applyItems(items, extractedAt) {
    storedItems = items ?? [];
    currentPage = 1;
    showLastExtraction(extractedAt);
    showStoredLayout();
  }

  async function loadCatalog() {
    const response = await fetch(config.endpoint);
    if (!response.ok) {
      throw new Error(config.loadError);
    }
    const data = await response.json();
    clearStatus();
    applyItems(data.items, data.extracted_at);
  }

  async function uploadFile(file) {
    const extension = file.name.split(".").pop()?.toLowerCase();
    if (extension !== "csv" && extension !== "xlsx") {
      setStatus("Upload a .csv or .xlsx file.", "error");
      return;
    }
    uploadButton.disabled = true;
    replaceButton.disabled = true;
    setStatus("Saving…", "success");
    try {
      const body = new FormData();
      body.append("file", file);
      const response = await fetch(config.endpoint, { method: "POST", body });
      const data = await response.json();
      if (data.ok) {
        applyItems(data.items, data.extracted_at);
        const count = data.count ?? storedItems.length;
        setStatus(`Saved ${count} ${count === 1 ? "entry" : "entries"}.`, "success");
        return;
      }
      if (data.rows) {
        const failing = data.rows.filter((entry) => Object.keys(entry.errors ?? {}).length > 0).length;
        setStatus(`${failing} ${failing === 1 ? "entry does" : "entries do"} not comply. Nothing was saved.`, "error");
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
    control.addEventListener("change", () => {
      filters[control.dataset.field] = control.value;
      currentPage = 1;
      renderStoredRows();
    });
  });

  uploadButton.addEventListener("click", () => fileInput.click());
  replaceButton.addEventListener("click", () => fileInput.click());
  addButton.addEventListener("click", () => config.onCreate());
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
    setStatus(error.message || config.loadError, "error");
  });

  return {
    setStatus,
    replaceItems(items, extractedAt, message) {
      applyItems(items, extractedAt);
      if (message) {
        setStatus(message, "success");
      }
    },
  };
}

function showMappedErrors(errors, fieldErrors) {
  Object.values(fieldErrors).forEach((id) => {
    const error = document.getElementById(id);
    error.hidden = true;
    error.textContent = "";
  });
  Object.entries(errors || {}).forEach(([key, message]) => {
    const error = document.getElementById(fieldErrors[key]);
    if (!error) {
      return;
    }
    error.hidden = false;
    error.textContent = message;
  });
}

function selectedValues(select) {
  return [...select.selectedOptions].map((option) => option.value).filter(Boolean);
}

function fillSelect(select, options, placeholder) {
  select.replaceChildren();
  if (placeholder) {
    const blank = document.createElement("option");
    blank.value = "";
    blank.textContent = placeholder;
    select.appendChild(blank);
  }
  options.forEach((option) => {
    const element = document.createElement("option");
    element.value = option.value;
    element.textContent = option.label;
    select.appendChild(element);
  });
}

function optionLabel(id, name) {
  return `${id} \u2014 ${name}`;
}
