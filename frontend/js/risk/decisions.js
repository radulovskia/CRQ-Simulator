const main = document.querySelector("main");
const statusBox = document.getElementById("status");

function setStatus(message, type) {
  statusBox.hidden = false;
  statusBox.textContent = message;
  statusBox.className = `status ${type}`;
}

function decisionState(status) {
  if (status === "Approved" || status === "Rejected") return status;
  return "Pending";
}

function groupedMoney(value) {
  if (value == null || value === "" || Number.isNaN(Number(value))) return "";
  return `¤ ${Number(value).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function formatDecisionTime(value) {
  const parsed = value ? new Date(value) : null;
  if (!parsed || Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

async function load() {
  const response = await fetch("/decisions");
  const data = await response.json();
  if (!response.ok) {
    setStatus(data.detail || "The decision log could not be loaded.", "error");
    return;
  }
  document.getElementById("decision-table")?.remove();
  const table = document.createElement("table");
  table.className = "inventory-table";
  table.innerHTML = "<thead><tr><th>Record</th><th>Title</th><th>Status</th><th>Current Annual Loss Expectancy</th><th>Appetite</th><th></th></tr></thead>";
  const body = document.createElement("tbody");
  (data.items || []).forEach((item) => {
    const row = document.createElement("tr");
    [item.record_id, item.title].forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.appendChild(cell);
    });
    const stateCell = document.createElement("td");
    const state = document.createElement("span");
    const label = decisionState(item.status);
    state.className = `decision-state decision-${label.toLowerCase()}`;
    state.textContent = label;
    if (label !== "Pending") {
      const when = formatDecisionTime(item.approved_at);
      const by = String(item.approved_by ?? "").trim();
      const lines = [];
      if (when) lines.push(when);
      lines.push(`By: ${by}`);
      state.title = lines.join("\n");
    }
    stateCell.appendChild(state);
    row.appendChild(stateCell);
    [groupedMoney(item.portfolio_current_mean), item.appetite_status || ""].forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.appendChild(cell);
    });
    const actions = document.createElement("td");
    actions.className = "row-actions";
    const pdf = document.createElement("button");
    pdf.type = "button";
    pdf.textContent = "PDF";
    pdf.addEventListener("click", () => download(item.record_id));
    const verify = document.createElement("button");
    verify.type = "button";
    verify.textContent = "Verify";
    verify.addEventListener("click", () => check(item.record_id));
    const decision = document.createElement("button");
    decision.type = "button";
    decision.textContent = "Decision";
    decision.addEventListener("click", () => openDecision(item));
    actions.append(pdf, verify, decision);
    row.appendChild(actions);
    body.appendChild(row);
  });
  table.appendChild(body);
  const section = document.createElement("section");
  section.id = "decision-table";
  section.className = "panel";
  section.appendChild(table);
  main.appendChild(section);
}

async function download(recordId) {
  const preview = window.open("about:blank", "_blank");
  if (!preview) {
    setStatus("Allow pop-ups to open the PDF in a new tab.", "error");
    return;
  }
  const response = await fetch(`/decisions/${recordId}`);
  const record = await response.json();
  if (!response.ok) {
    preview.close();
    setStatus(record.detail || "That decision record was not found.", "error");
    return;
  }
  renderBoardReport(record.report, preview);
}

async function check(recordId) {
  const response = await fetch(`/decisions/${recordId}/verify`);
  const result = await response.json();
  setStatus(result.valid ? `${recordId} hash is valid.` : `${recordId} hash does not match.`, result.valid ? "success" : "error");
}

const decisionModal = document.getElementById("decision-modal");
const decisionForm = document.getElementById("decision-form");
const decisionEditor = document.getElementById("decision-editor");
const decisionRecord = document.getElementById("decision-record");
const decisionSave = document.getElementById("decision-save");
const decisionCancel = document.getElementById("decision-cancel");
const decisionChoice = document.getElementById("decision-choice");
const decisionNote = document.getElementById("decision-note");
const decisionBy = document.getElementById("decision-by");
let activeRecord = null;

function showFieldError(id, message) {
  const error = document.getElementById(id);
  error.hidden = !message;
  error.textContent = message || "";
}

function showDecisionEditor() {
  decisionEditor.hidden = false;
  decisionRecord.hidden = true;
  decisionSave.hidden = false;
  decisionCancel.textContent = "Cancel";
}

function openDecision(item) {
  document.getElementById("decision-title").textContent = `Decision ${item.record_id}`;
  if (item.status === "Approved" || item.status === "Rejected") {
    showRecordedDecision(item.record_id);
    return;
  }
  activeRecord = item.record_id;
  showDecisionEditor();
  decisionChoice.value = "";
  decisionNote.value = "";
  decisionBy.value = "";
  showFieldError("error-decision", "");
  showFieldError("error-note", "");
  showFieldError("error-by", "");
  decisionModal.hidden = false;
  decisionChoice.focus();
}

async function showRecordedDecision(recordId) {
  const response = await fetch(`/decisions/${recordId}`);
  const record = await response.json();
  if (!response.ok) {
    setStatus(record.detail || "That decision record was not found.", "error");
    return;
  }
  activeRecord = null;
  document.getElementById("decision-view-choice").textContent = decisionState(record.status);
  document.getElementById("decision-view-note").textContent = record.approval_note || "";
  document.getElementById("decision-view-by").textContent = record.approved_by || "";
  document.getElementById("decision-view-when").textContent = formatDecisionTime(record.approved_at);
  decisionEditor.hidden = true;
  decisionRecord.hidden = false;
  decisionSave.hidden = true;
  decisionCancel.textContent = "Close";
  decisionModal.hidden = false;
  decisionCancel.focus();
}

function closeDecision() {
  decisionModal.hidden = true;
  activeRecord = null;
  showDecisionEditor();
}

async function saveDecision(event) {
  event.preventDefault();
  const status = decisionChoice.value;
  const note = decisionNote.value.trim();
  const approvedBy = decisionBy.value.trim();
  const choiceError = status === "Approved" || status === "Rejected" ? "" : "must not be empty";
  const noteError = note ? "" : "must not be empty";
  const byError = approvedBy ? "" : "must not be empty";
  showFieldError("error-decision", choiceError);
  showFieldError("error-note", noteError);
  showFieldError("error-by", byError);
  if (choiceError || noteError || byError || !activeRecord || decisionEditor.hidden) return;
  const recordId = activeRecord;
  const saveButton = decisionSave;
  saveButton.disabled = true;
  try {
    const response = await fetch(`/decisions/${recordId}/approval`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status, approved_by: approvedBy, note }),
    });
    const record = await response.json();
    if (!response.ok) {
      setStatus(record.detail || "The decision pack could not be updated.", "error");
      return;
    }
    closeDecision();
    setStatus(`${recordId} is ${decisionState(record.status)}.`, "success");
    await load();
  } catch (error) {
    setStatus(error.message || "The decision pack could not be updated.", "error");
  } finally {
    saveButton.disabled = false;
  }
}

decisionForm.addEventListener("submit", saveDecision);
decisionCancel.addEventListener("click", closeDecision);
decisionModal.addEventListener("click", (event) => {
  if (event.target === decisionModal) closeDecision();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !decisionModal.hidden) closeDecision();
});

load().catch((error) => setStatus(error.message, "error"));
