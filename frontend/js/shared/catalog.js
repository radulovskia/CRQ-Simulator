function numericComparison(query) {
  const match = /^(<=|>=|<|>|=)\s*(-?\d+(?:\.\d+)?)$/.exec(query.trim());
  if (!match) return null;
  return { operator: match[1], target: Number(match[2]) };
}

function numericValue(value) {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (value == null) return null;
  const match = /^(-?\d+(?:\.\d+)?)(?:\s*(?:%|\([^)]*\)))?$/.exec(String(value).trim());
  if (!match) return null;
  const number = Number(match[1]);
  return Number.isFinite(number) ? number : null;
}

function matchesNumeric(value, comparison) {
  const number = numericValue(value);
  if (number == null) return false;
  switch (comparison.operator) {
    case "<":
      return number < comparison.target;
    case ">":
      return number > comparison.target;
    case "<=":
      return number <= comparison.target;
    case ">=":
      return number >= comparison.target;
    case "=":
      return number === comparison.target;
    default:
      return false;
  }
}

function filterSearch(field) {
  const input = document.createElement("input");
  input.type = "search";
  input.dataset.field = field.key;
  input.placeholder = "Filter";
  input.setAttribute("aria-label", `Filter ${field.label}`);
  return input;
}

function filterSelect(field) {
  const select = document.createElement("select");
  select.dataset.field = field.key;
  select.setAttribute("aria-label", `Filter ${field.label}`);
  const all = document.createElement("option");
  all.value = "";
  all.textContent = "All";
  select.appendChild(all);
  field.options.forEach((option) => {
    const element = document.createElement("option");
    element.value = option;
    element.textContent = option;
    select.appendChild(element);
  });
  return select;
}

function csvCell(value) {
  const text = value == null ? "" : String(value);
  if (/[",\r\n]/.test(text)) return `"${text.replaceAll('"', '""')}"`;
  return text;
}

function catalogFilename() {
  const name = (document.querySelector("h1")?.textContent || "Catalog").trim().replace(/\s+/g, "_");
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${name}_${now.getFullYear()}${month}${day}.csv`;
}

function downloadCsv(headers, keys, items) {
  const lines = [headers.map(csvCell).join(",")];
  items.forEach((item) => {
    lines.push(keys.map((key) => csvCell(item[key])).join(","));
  });
  const blob = new Blob([`${lines.join("\r\n")}\r\n`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = catalogFilename();
  link.click();
  URL.revokeObjectURL(url);
}

function mountCatalog(config) {
  const uploadPanel = document.getElementById("upload-panel");
  const dropzone = document.getElementById("dropzone");
  const uploadButton = document.getElementById("upload-button");
  const replaceButton = document.getElementById("replace-button");
  const exportButton = document.createElement("button");
  exportButton.type = "button";
  exportButton.className = "inventory-replace";
  exportButton.textContent = "Export Catalog";
  exportButton.hidden = true;
  const headerActions = document.createElement("div");
  headerActions.className = "header-actions";
  replaceButton.replaceWith(headerActions);
  headerActions.append(exportButton, replaceButton);
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
  const storedHead = document.querySelector("#stored thead");
  if (storedHead && !storedHead.children.length && config.fields.every((field) => field.label)) {
    const header = document.createElement("tr");
    const filters = document.createElement("tr");
    filters.className = "filter-row";
    config.fields.forEach((field) => {
      const heading = document.createElement("th");
      heading.setAttribute("aria-sort", "none");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "sort-button";
      button.dataset.field = field.key;
      button.append(document.createTextNode(field.label));
      const indicator = document.createElement("span");
      indicator.className = "sort-indicator";
      indicator.setAttribute("aria-hidden", "true");
      button.appendChild(indicator);
      heading.appendChild(button);
      header.appendChild(heading);
      const filterCell = document.createElement("th");
      filterCell.appendChild(field.options ? filterSelect(field) : filterSearch(field));
      filters.appendChild(filterCell);
    });
    const editHeading = document.createElement("th");
    editHeading.className = "edit-heading";
    header.appendChild(editHeading);
    filters.appendChild(document.createElement("th"));
    storedHead.append(header, filters);
  }

  const sortButtons = [...document.querySelectorAll(".sort-button")];
  const filterControls = [...document.querySelectorAll(".filter-row [data-field]")];
  const timestampFormat = { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" };

  let storedItems = [];
  let sortField = null;
  let sortDirection = "asc";
  let currentPage = 1;
  let enrichToken = 0;
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

  function groupedNumber(value) {
    return Number(value).toLocaleString(undefined, { maximumFractionDigits: 4 });
  }

  function showTotalCount(count) {
    totalCount.hidden = !count;
    totalCount.textContent = count ? `Total Count: ${groupedNumber(count)}` : "";
  }

  function displayValue(item, field) {
    const value = typeof field === "string" ? item[field] : item[field.key];
    if (typeof field === "object" && field.format === "money") {
      if (value === undefined || value === "") return "…";
      if (value == null || Number.isNaN(Number(value))) return "N/A";
      return `¤ ${Number(value).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
    }
    if (typeof value === "number" && Number.isFinite(value)) {
      return groupedNumber(value);
    }
    const nullable = typeof field === "object" && field.nullable;
    if (nullable && (value === null || value === undefined || value === "")) {
      return "Unknown";
    }
    return value ?? "";
  }

  function compareValues(field, left, right) {
    const rank = config.ranks?.[field];
    if (rank) {
      return (rank[left[field]] ?? 99) - (rank[right[field]] ?? 99);
    }
    const leftValue = left[field];
    const rightValue = right[field];
    if (typeof leftValue === "number" || typeof rightValue === "number") {
      const leftNumber = typeof leftValue === "number" ? leftValue : Number.POSITIVE_INFINITY;
      const rightNumber = typeof rightValue === "number" ? rightValue : Number.POSITIVE_INFINITY;
      return leftNumber - rightNumber;
    }
    return String(leftValue ?? "").localeCompare(String(rightValue ?? ""), undefined, {
      numeric: true,
      sensitivity: "base",
    });
  }

  function matchesText(value, query) {
    return String(value ?? "").toLocaleLowerCase().includes(query.toLocaleLowerCase());
  }

  function matchesField(item, field) {
    const query = (filters[field.key] || "").trim();
    if (query) {
      const control = filterControls.find((element) => element.dataset.field === field.key);
      if (control?.tagName === "SELECT") {
        if (item[field.key] !== query) return false;
      } else {
        const values = [displayValue(item, field)];
        if (typeof item[field.key] === "number") values.push(item[field.key]);
        if (field.detail) values.push(item[field.detail.key]);
        const comparison = numericComparison(query);
        const matched = comparison
          ? values.some((value) => matchesNumeric(value, comparison))
          : values.some((value) => matchesText(value, query));
        if (!matched) return false;
      }
    }
    return true;
  }

  function visibleItems() {
    const matched = storedItems.filter((item) => config.fields.every((field) => matchesField(item, field)));
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

  function trashIcon() {
    const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    icon.setAttribute("viewBox", "0 0 24 24");
    icon.setAttribute("aria-hidden", "true");
    icon.classList.add("trash-icon");
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("fill", "currentColor");
    path.setAttribute(
      "d",
      "M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z",
    );
    icon.appendChild(path);
    return icon;
  }

  async function deleteItem(item) {
    const label = config.deleteKeys.map((key) => item[key]).filter(Boolean).join(" / ");
    if (!window.confirm(`Delete ${label}?`)) {
      return;
    }
    const params = new URLSearchParams();
    config.deleteKeys.forEach((key) => params.set(key, item[key] ?? ""));
    const response = await fetch(`${config.endpoint}/entry?${params}`, { method: "DELETE" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) {
      setStatus(data.error || "The entry could not be deleted.", "error");
      return;
    }
    applyItems(data.items, data.extracted_at);
    setStatus("Entry deleted.", "success");
  }

  function fillCell(cell, item, field) {
    const mainText = String(displayValue(item, field));
    if (field.titleKey) {
      cell.textContent = mainText;
      const title = String(item[field.titleKey] ?? "");
      if (title) cell.title = title;
      return;
    }
    if (!field.detail) {
      cell.textContent = mainText;
      return;
    }
    const detailText = String(item[field.detail.key] ?? "");
    const main = document.createElement("div");
    main.textContent = mainText;
    cell.appendChild(main);
    const note = document.createElement("div");
    note.className = "cell-detail";
    note.textContent = detailText;
    cell.appendChild(note);
    if (field.detail.title) cell.title = `Owner: ${mainText}\nCustodian: ${detailText}`;
  }

  function renderStoredRows() {
    updateSortIndicators();
    const visible = visibleItems();
    const filtered = visible.length !== storedItems.length;
    catalogCount.hidden = !filtered;
    catalogCount.textContent = filtered ? `Showing ${groupedNumber(visible.length)} of ${groupedNumber(storedItems.length)}` : "";
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
          if (field.className) cell.className = field.className;
          fillCell(cell, item, field);
          row.appendChild(cell);
        });
        const editCell = document.createElement("td");
        editCell.className = "edit-cell";
        const actions = config.rowActions || [];
        const stack = actions.length ? document.createElement("div") : null;
        if (stack) {
          stack.className = "row-action-stack";
          editCell.appendChild(stack);
        }
        const iconRow = actions.length ? document.createElement("div") : editCell;
        if (actions.length) {
          iconRow.className = "row-action-icons";
          stack.appendChild(iconRow);
        }
        const editButton = document.createElement("button");
        editButton.type = "button";
        editButton.className = "icon-button";
        editButton.setAttribute("aria-label", "Edit");
        editButton.appendChild(pencilIcon());
        editButton.addEventListener("click", () => config.onEdit(item));
        iconRow.appendChild(editButton);
        if (config.deleteKeys?.length) {
          const deleteButton = document.createElement("button");
          deleteButton.type = "button";
          deleteButton.className = "icon-button delete-button";
          deleteButton.setAttribute("aria-label", "Delete");
          deleteButton.appendChild(trashIcon());
          deleteButton.addEventListener("click", () => deleteItem(item));
          iconRow.appendChild(deleteButton);
        }
        actions.forEach((action) => {
          const button = document.createElement("button");
          button.type = "button";
          button.textContent = action.label;
          button.addEventListener("click", () => action.onClick(item));
          stack.appendChild(button);
        });
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

  function showCatalogActions(hasRows) {
    const canExport = hasRows && config.exportKeys?.length === config.reviewColumns.length;
    replaceButton.hidden = !hasRows;
    exportButton.hidden = !canExport;
  }

  function showStoredLayout() {
    reviewSection.hidden = true;
    const hasRows = storedItems.length > 0;
    uploadPanel.hidden = hasRows;
    showCatalogActions(hasRows);
    storedSection.hidden = !hasRows;
    showTotalCount(hasRows ? storedItems.length : 0);
    if (hasRows) {
      renderStoredRows();
    }
  }

  const REVIEW_LABELS = {
    "OU ID": "Organisational Unit ID",
    "BP ID": "Business Process ID",
    "RTO (hours)": "Recovery Time Objective (hours)",
    "Downtime Cost per Hour before RTO": "Downtime Cost per Hour before Recovery Time Objective",
    "Downtime Cost per Hour post RTO": "Downtime Cost per Hour post Recovery Time Objective",
    "FTE Count": "Full-Time Equivalent Count",
    "Business Owner OU ID": "Business Owner Organisational Unit ID",
    "Technical Custodian OU ID": "Technical Custodian Organisational Unit ID",
    "Owner OU ID": "Owner Organisational Unit ID",
    "Risk Owner OU ID": "Risk Owner Organisational Unit ID",
    "Base TEF Min": "Base Threat Event Frequency Min",
    "Base TEF Mode": "Base Threat Event Frequency Mode",
    "Base TEF Max": "Base Threat Event Frequency Max",
    "TEF Min": "Threat Event Frequency Min",
    "TEF Mode": "Threat Event Frequency Mode",
    "TEF Max": "Threat Event Frequency Max",
    "TEF Basis": "Threat Event Frequency Basis",
    "PURL": "Package URL",
  };

  function showReview(rows) {
    reviewHead.replaceChildren();
    const headRow = document.createElement("tr");
    ["Row", ...config.reviewColumns].forEach((label) => {
      const cell = document.createElement("th");
      cell.textContent = REVIEW_LABELS[label] || label;
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
    showCatalogActions(hasRows);
    storedSection.hidden = true;
    reviewSection.hidden = false;
  }

  function applyItems(items, extractedAt) {
    const rows = items ?? [];
    const token = ++enrichToken;
    storedItems = rows;
    currentPage = 1;
    showLastExtraction(extractedAt);
    showStoredLayout();
    if (!config.enrich || !rows.length) return;
    config.enrich(rows).then((enriched) => {
      if (token !== enrichToken) return;
      storedItems = enriched;
      showStoredLayout();
    }).catch((error) => {
      if (token !== enrichToken) return;
      setStatus(error.message || "The scenario results could not be loaded.", "error");
    });
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
    exportButton.disabled = true;
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
      exportButton.disabled = false;
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
  exportButton.addEventListener("click", () => {
    if (!storedItems.length || config.exportKeys?.length !== config.reviewColumns.length) return;
    downloadCsv(config.reviewColumns, config.exportKeys, storedItems);
  });
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
  return `${id} - ${name}`;
}

async function catalogOptions(endpoint, idKey, nameKey) {
  const response = await fetch(endpoint);
  if (!response.ok) {
    throw new Error("The related records could not be loaded.");
  }
  const data = await response.json();
  return (data.items || []).map((item) => ({
    value: String(item[idKey] ?? ""),
    label: optionLabel(item[idKey], item[nameKey]),
  }));
}

function mountEntryForm(config) {
  const modal = document.getElementById("entry-modal");
  const form = document.getElementById("entry-form");
  const title = document.getElementById("entry-title");
  const fieldsHost = document.getElementById("entry-fields");
  let previous = null;

  function fieldId(name) {
    return `field-${name}`;
  }

  function errorId(name) {
    return `error-${name}`;
  }

  function buildControl(field) {
    const input = field.options || field.choices
      ? document.createElement("select")
      : document.createElement("input");
    input.id = fieldId(field.name);
    if (field.choices?.multiple) input.multiple = true;
    if (field.options) {
      field.options.forEach((option) => {
        const element = document.createElement("option");
        element.value = option;
        element.textContent = option || "Unknown";
        input.appendChild(element);
      });
    } else if (!field.choices) {
      input.type = field.kind === "number" ? "number" : "text";
      if (field.kind === "number") input.step = "any";
    }
    const error = document.createElement("span");
    error.id = errorId(field.name);
    error.className = "field-error";
    error.hidden = true;
    return { input, error };
  }

  function buildField(field) {
    const label = document.createElement("label");
    label.className = "field";
    label.append(document.createTextNode(field.label));
    const control = buildControl(field);
    label.append(control.input, control.error);
    return label;
  }

  function buildTriple(min, mode, max) {
    const group = document.createElement("div");
    group.className = "field field-triple";
    const name = document.createElement("span");
    name.className = "triple-name";
    name.textContent = min.label.replace(/\s+Min$/, "");
    const row = document.createElement("div");
    row.className = "triple-row";
    [["Min", min], ["Mode", mode], ["Max", max]].forEach(([part, field]) => {
      const label = document.createElement("label");
      label.className = "triple-part";
      label.append(document.createTextNode(part));
      const control = buildControl(field);
      label.append(control.input, control.error);
      row.appendChild(label);
    });
    group.append(name, row);
    return group;
  }

  const blocks = [];
  for (let index = 0; index < config.fields.length; index += 1) {
    const min = config.fields[index];
    const mode = config.fields[index + 1];
    const max = config.fields[index + 2];
    const prefix = min.name.match(/^(.*)_min$/)?.[1];
    if (prefix && mode?.name === `${prefix}_mode` && max?.name === `${prefix}_max`) {
      blocks.push(buildTriple(min, mode, max));
      index += 2;
    } else {
      blocks.push(buildField(min));
    }
  }
  fieldsHost.replaceChildren(...blocks);

  const mapped = Object.fromEntries(config.fields.map((field) => [field.header || field.label, errorId(field.name)]));

  function values() {
    const payload = {};
    config.fields.forEach((field) => {
      const input = document.getElementById(fieldId(field.name));
      if (field.choices?.multiple) {
        payload[field.name] = selectedValues(input).join(", ");
        return;
      }
      const raw = input.value.trim();
      if (field.kind === "number") {
        payload[field.name] = raw === "" ? null : Number(raw);
      } else {
        payload[field.name] = raw;
      }
    });
    return payload;
  }

  function rememberOption(select, value) {
    if (!value || [...select.options].some((option) => option.value === value)) return;
    const extra = document.createElement("option");
    extra.value = value;
    extra.textContent = value;
    select.appendChild(extra);
  }

  async function refreshChoices(field, raw) {
    const select = document.getElementById(fieldId(field.name));
    const options = typeof field.choices.load === "function"
      ? await field.choices.load(values())
      : await catalogOptions(field.choices.endpoint, field.choices.id, field.choices.name);
    fillSelect(select, options, field.choices.multiple ? "" : "Select");
    if (field.choices.multiple) {
      const selected = new Set(String(raw ?? "").split(",").map((part) => part.trim()).filter(Boolean));
      selected.forEach((value) => rememberOption(select, value));
      [...select.options].forEach((option) => {
        option.selected = selected.has(option.value);
      });
      return;
    }
    rememberOption(select, raw ?? "");
    select.value = raw ?? "";
  }

  async function open(item) {
    previous = item ? item[config.idKey] : null;
    title.textContent = previous ? config.editTitle : config.addTitle;
    if (config.secondaryKey && item) previous = { primary: item[config.idKey], secondary: item[config.secondaryKey] };
    showMappedErrors({}, mapped);
    config.fields.forEach((field) => {
      if (field.choices) return;
      const input = document.getElementById(fieldId(field.name));
      const next = String(item?.[field.name] ?? "");
      const matched = input.tagName === "SELECT" && [...input.options].some((option) => option.value === next);
      input.value = matched || input.tagName !== "SELECT" ? next : (input.options[0]?.value ?? "");
    });
    try {
      const linked = config.fields.filter((field) => field.choices);
      await Promise.all(linked.filter((field) => !field.choices.dependsOn).map((field) => refreshChoices(field, item?.[field.name] ?? "")));
      await Promise.all(linked.filter((field) => field.choices.dependsOn).map((field) => refreshChoices(field, item?.[field.name] ?? "")));
    } catch (error) {
      config.catalog.setStatus(error.message || "The related records could not be loaded.", "error");
      return false;
    }
    modal.hidden = false;
    return true;
  }

  function close() {
    modal.hidden = true;
    previous = null;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = values();
    if (previous && config.previousKey) {
      if (typeof previous === "object") {
        payload[config.previousKey] = previous.primary;
        payload[config.previousSecondaryKey] = previous.secondary;
      } else {
        payload[config.previousKey] = previous;
      }
    }
    const response = await fetch(config.endpoint, {
      method: previous ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!data.ok) {
      showMappedErrors(data.errors || {}, mapped);
      if (data.error) config.catalog.setStatus(data.error, "error");
      return;
    }
    const edited = previous != null;
    close();
    config.catalog.replaceItems(data.items, data.extracted_at, edited ? "Entry updated." : "Entry added.");
  });

  config.fields.forEach((field) => {
    if (!field.choices?.dependsOn) return;
    document.getElementById(fieldId(field.choices.dependsOn)).addEventListener("change", () => {
      refreshChoices(field, "").catch((error) => {
        config.catalog.setStatus(error.message || "The related records could not be loaded.", "error");
      });
    });
  });

  document.getElementById("entry-cancel").addEventListener("click", close);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.hidden) close();
  });
  return { open, close };
}
