const TYPES = [
  ["tactics", "Tactics"],
  ["techniques", "Techniques"],
  ["groups", "Groups"],
  ["software", "Software"],
  ["mitigations", "Mitigations"],
  ["campaigns", "Campaigns"],
  ["assets", "Assets"],
  ["detection-strategies", "Detection Strategies"],
  ["analytics", "Analytics"],
  ["data-components", "Data Components"],
];

const statusBox = document.getElementById("status");
const meta = document.getElementById("dataset-meta");
const browser = document.getElementById("browser");
const typeSwitch = document.getElementById("type-switch");
const search = document.getElementById("search");
const showDeprecatedButton = document.getElementById("show-deprecated");
const resultCount = document.getElementById("result-count");
const body = document.getElementById("mitre-body");
const pager = document.getElementById("mitre-pager");
const detailModal = document.getElementById("detail-modal");
const detail = document.getElementById("detail");
const detailClose = document.getElementById("detail-close");
const checkButton = document.getElementById("check-button");
const categoryFilter = document.getElementById("category-filter");
const categoryToggle = document.getElementById("category-toggle");
const categoryMenu = document.getElementById("category-menu");

const CATEGORY_TYPES = new Set(["tactics", "techniques", "software", "assets", "analytics"]);

let currentType = "tactics";
let items = [];
let page = 1;
let selectedId = "";
let sortField = null;
let sortDirection = "asc";
let showDeprecated = false;
let selectedCategory = "";

TYPES.forEach(([name, label]) => {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.dataset.type = name;
  button.setAttribute("aria-pressed", String(name === currentType));
  button.addEventListener("click", () => {
    currentType = name;
    page = 1;
    selectedId = "";
    closeDetail();
    search.value = "";
    selectedCategory = "";
    closeCategoryMenu();
    typeSwitch.querySelectorAll("button").forEach((item) => {
      item.setAttribute("aria-pressed", String(item.dataset.type === name));
    });
    loadType(name);
  });
  typeSwitch.appendChild(button);
});

function setStatus(message, type) {
  statusBox.hidden = false;
  statusBox.textContent = message;
  statusBox.className = `status ${type}`;
}

function formatTimestamp(value) {
  const parsed = value ? new Date(value) : null;
  if (!parsed || Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function showDataset(status) {
  if (!status.loaded) {
    meta.hidden = true;
    browser.hidden = true;
    return;
  }
  const when = formatTimestamp(status.downloaded_at);
  meta.hidden = false;
  meta.textContent = when
    ? `Enterprise ATT&CK ${status.attack_version}, loaded ${when}.`
    : `Enterprise ATT&CK ${status.attack_version}.`;
  browser.hidden = false;
}

function decodeEntities(value) {
  const textarea = document.createElement("textarea");
  textarea.innerHTML = value.replace(/</g, "&lt;");
  return textarea.value;
}

function appendRichText(parent, text) {
  const pattern = /\[([^\]\n]+)\]\((https?:\/\/[^)\s]+)\)|<code>([\s\S]*?)<\/code>/gi;
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index > last) parent.append(document.createTextNode(text.slice(last, match.index)));
    if (match[3] !== undefined) {
      const code = document.createElement("code");
      code.textContent = decodeEntities(match[3]);
      parent.appendChild(code);
    } else {
      const link = document.createElement("a");
      link.href = match[2];
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = match[1];
      parent.appendChild(link);
    }
    last = match.index + match[0].length;
  }
  if (last < text.length) parent.append(document.createTextNode(text.slice(last)));
}

function splitOutsideCode(text) {
  const lines = [];
  let current = "";
  let inCode = false;
  for (let index = 0; index < text.length; index += 1) {
    const slice = text.slice(index, index + 7).toLowerCase();
    if (!inCode && slice.startsWith("<code>")) inCode = true;
    else if (inCode && slice.startsWith("</code>")) inCode = false;
    if (text[index] === "\n" && !inCode) {
      lines.push(current);
      current = "";
    } else {
      current += text[index];
    }
  }
  lines.push(current);
  return lines;
}

function appendBlocks(parent, text) {
  let paragraph = [];
  let list = null;

  function flushParagraph() {
    const content = paragraph.join("\n").replace(/^\n+|\n+$/g, "");
    paragraph = [];
    if (!content) return;
    const block = document.createElement("p");
    appendRichText(block, content);
    parent.appendChild(block);
  }

  splitOutsideCode(text).forEach((line) => {
    const bullet = line.match(/^\* ([\s\S]*)$/);
    if (bullet) {
      flushParagraph();
      if (!list) {
        list = document.createElement("ul");
        list.className = "mitre-bullets";
        parent.appendChild(list);
      }
      const item = document.createElement("li");
      appendRichText(item, bullet[1]);
      list.appendChild(item);
      return;
    }
    list = null;
    paragraph.push(line);
  });
  flushParagraph();
}

function referenceLabel(item) {
  if (item.source_name === "mitre-attack") return "MITRE ATT&CK";
  return item.source_name || item.url;
}

function closeDetail() {
  detailModal.hidden = true;
}

function detailText(item) {
  const flags = [item.revoked ? "revoked" : "", item.deprecated ? "deprecated" : ""].filter(Boolean).join(", ");
  return [item.summary, flags].filter(Boolean).join(" · ");
}

function categoryParts(summary) {
  return String(summary || "").split(",").map((part) => part.trim()).filter(Boolean);
}

function categoryOptions() {
  const values = new Set();
  items.forEach((item) => {
    if (!showDeprecated && item.deprecated) return;
    categoryParts(item.summary).forEach((part) => values.add(part));
  });
  return [...values].sort((left, right) => left.localeCompare(right, undefined, { sensitivity: "base" }));
}

function closeCategoryMenu() {
  categoryMenu.hidden = true;
  categoryToggle.setAttribute("aria-expanded", "false");
}

function placeCategoryMenu() {
  const rect = categoryToggle.getBoundingClientRect();
  categoryMenu.style.top = `${rect.bottom + 6}px`;
  categoryMenu.style.left = `${Math.min(rect.left, window.innerWidth - categoryMenu.offsetWidth - 8)}px`;
}

function renderCategoryFilter() {
  closeCategoryMenu();
  if (!CATEGORY_TYPES.has(currentType)) {
    categoryFilter.hidden = true;
    selectedCategory = "";
    categoryToggle.dataset.active = "false";
    categoryMenu.replaceChildren();
    return;
  }
  const options = categoryOptions();
  if (!options.includes(selectedCategory)) selectedCategory = "";
  categoryFilter.hidden = false;
  categoryToggle.dataset.active = String(Boolean(selectedCategory));
  categoryMenu.replaceChildren();
  ["All", ...options].forEach((value) => {
    const item = document.createElement("li");
    item.setAttribute("role", "none");
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("role", "menuitemradio");
    button.setAttribute("aria-checked", String((value === "All" && !selectedCategory) || value === selectedCategory));
    button.textContent = value;
    button.addEventListener("click", () => {
      selectedCategory = value === "All" ? "" : value;
      closeCategoryMenu();
      page = 1;
      renderCategoryFilter();
      renderTable();
    });
    item.appendChild(button);
    categoryMenu.appendChild(item);
  });
}

function matchesCategory(item) {
  const category = selectedCategory.trim().toLowerCase();
  if (!category || categoryFilter.hidden) return true;
  return String(item.summary || "").toLowerCase().includes(category);
}

function filteredItems() {
  const query = search.value.trim().toLowerCase();
  return items.filter((item) => {
    if (!showDeprecated && item.deprecated) return false;
    if (!matchesCategory(item)) return false;
    if (!query) return true;
    return [item.external_id, item.name, item.summary].join(" ").toLowerCase().includes(query);
  });
}

function sortValue(item, field) {
  return field === "details" ? detailText(item) : item[field] ?? "";
}

function orderedItems() {
  const visible = filteredItems();
  if (!sortField) return visible;
  const direction = sortDirection === "desc" ? -1 : 1;
  return visible.slice().sort((left, right) => direction * String(sortValue(left, sortField)).localeCompare(String(sortValue(right, sortField)), undefined, {
    numeric: true,
    sensitivity: "base",
  }));
}

function updateSortIndicators() {
  document.querySelectorAll(".sort-button").forEach((button) => {
    const active = button.dataset.field === sortField;
    button.closest("th").setAttribute("aria-sort", active ? (sortDirection === "asc" ? "ascending" : "descending") : "none");
    button.querySelector(".sort-indicator").textContent = active ? (sortDirection === "asc" ? "▲" : "▼") : "";
  });
}

function renderTable() {
  const visible = orderedItems();
  updateSortIndicators();
  page = clampPage(visible.length, page);
  resultCount.hidden = false;
  resultCount.textContent = `${visible.length.toLocaleString()} ${visible.length === 1 ? "object" : "objects"}`;
  body.replaceChildren();
  pageItems(visible, page).forEach((item) => {
    const row = document.createElement("tr");
    row.tabIndex = 0;
    row.setAttribute("aria-selected", String(item.external_id === selectedId));
    [item.external_id, item.name, detailText(item)].forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.appendChild(cell);
    });
    row.addEventListener("click", () => openObject(item.external_id));
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter") openObject(item.external_id);
    });
    body.appendChild(row);
  });
  renderPager(pager, visible.length, page, (next) => {
    page = next;
    renderTable();
  });
}

async function loadType(type) {
  const response = await fetch(`/mitre/${type}`);
  const data = await response.json();
  if (!response.ok) {
    setStatus(data.detail || "The ATT&CK objects could not be loaded.", "error");
    return;
  }
  items = data.items || [];
  renderCategoryFilter();
  renderTable();
}

async function openObject(externalId) {
  if (!externalId) return;
  selectedId = externalId;
  renderTable();
  const response = await fetch(`/mitre/objects/${encodeURIComponent(externalId)}`);
  const data = await response.json();
  if (!response.ok) {
    setStatus(data.detail || "That ATT&CK object could not be loaded.", "error");
    return;
  }
  detail.hidden = false;
  detailModal.hidden = false;
  detail.replaceChildren();
  const heading = document.createElement("h2");
  heading.id = "detail-title";
  heading.textContent = data.external_id ? `${data.name} (${data.external_id})` : data.name;
  detail.appendChild(heading);
  const flags = [data.revoked ? "Revoked" : "", data.deprecated ? "Deprecated" : ""].filter(Boolean);
  if (flags.length || data.aliases.length) {
    const note = document.createElement("p");
    note.className = "mitre-meta";
    const aliasText = data.aliases.length ? `Also known as ${data.aliases.join(", ")}` : "";
    note.textContent = [flags.join(", "), aliasText].filter(Boolean).join(". ");
    detail.appendChild(note);
  }
  if (data.description) appendBlocks(detail, data.description);
  const references = data.references.filter((item) => item.url || item.description);
  if (references.length) {
    const list = document.createElement("ul");
    list.className = "mitre-relationships";
    references.forEach((item) => {
      const entry = document.createElement("li");
      if (item.url) {
        const link = document.createElement("a");
        link.href = item.url;
        link.target = "_blank";
        link.rel = "noreferrer";
        link.textContent = referenceLabel(item);
        entry.appendChild(link);
      } else {
        entry.append(referenceLabel(item));
      }
      if (item.description) {
        entry.append(" — ");
        appendRichText(entry, item.description);
      }
      list.appendChild(entry);
    });
    detail.appendChild(list);
  }
  if (data.relationships.length) {
    const list = document.createElement("ul");
    list.className = "mitre-relationships";
    data.relationships.forEach((item) => {
      const entry = document.createElement("li");
      entry.append(`${item.label}: `);
      if (item.external_id) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = item.external_id;
        button.addEventListener("click", () => openObject(item.external_id));
        entry.append(button, ` ${item.name}`);
      } else {
        entry.append(item.name);
        if (item.description) {
          entry.append(" — ");
          appendRichText(entry, item.description);
        }
      }
      list.appendChild(entry);
    });
    detail.appendChild(list);
  }
}

checkButton.addEventListener("click", async () => {
  checkButton.disabled = true;
  try {
    const response = await fetch("/mitre/check", { method: "POST" });
    const data = await response.json();
    if (!response.ok) {
      setStatus(data.error || data.detail || "The MITRE release could not be checked.", "error");
      return;
    }
    setStatus(data.message, "success");
    showDataset(data);
    if (data.loaded) await loadType(currentType);
  } catch (error) {
    setStatus(error.message || "The MITRE release could not be checked.", "error");
  } finally {
    checkButton.disabled = false;
  }
});

document.querySelectorAll(".sort-button").forEach((button) => {
  button.addEventListener("click", () => {
    if (sortField === button.dataset.field) {
      sortDirection = sortDirection === "asc" ? "desc" : "asc";
    } else {
      sortField = button.dataset.field;
      sortDirection = "asc";
    }
    page = 1;
    renderTable();
  });
});

detailClose.addEventListener("click", closeDetail);
detailModal.addEventListener("click", (event) => {
  if (event.target === detailModal) closeDetail();
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (!categoryMenu.hidden) {
    closeCategoryMenu();
    categoryToggle.focus();
    return;
  }
  if (!detailModal.hidden) closeDetail();
});

categoryToggle.addEventListener("click", (event) => {
  event.stopPropagation();
  if (categoryFilter.hidden) return;
  const open = categoryMenu.hidden;
  categoryMenu.hidden = !open;
  categoryToggle.setAttribute("aria-expanded", String(open));
  if (open) placeCategoryMenu();
});

document.addEventListener("click", (event) => {
  if (!categoryMenu.hidden && !categoryFilter.contains(event.target)) closeCategoryMenu();
});

window.addEventListener("resize", () => {
  if (!categoryMenu.hidden) placeCategoryMenu();
});

window.addEventListener("scroll", () => {
  if (!categoryMenu.hidden) placeCategoryMenu();
}, true);

search.addEventListener("input", () => {
  page = 1;
  renderTable();
});

showDeprecatedButton.addEventListener("click", () => {
  showDeprecated = !showDeprecated;
  showDeprecatedButton.setAttribute("aria-pressed", String(showDeprecated));
  page = 1;
  renderCategoryFilter();
  renderTable();
});

fetch("/mitre/status")
  .then((response) => response.json())
  .then(async (status) => {
    showDataset(status);
    if (status.loaded) await loadType(currentType);
  })
  .catch((error) => setStatus(error.message || "The MITRE dataset could not be loaded.", "error"));
