const INDEPENDENCE = "Portfolio figures assume Risk Scenarios are independent: portfolio annual loss is the per-iteration sum of scenario losses; no correlation between scenarios is modelled.";

const main = document.querySelector("main");
const statusBox = document.getElementById("status");
const appetiteModal = document.getElementById("entry-modal");
const appetiteForm = document.getElementById("entry-form");
const appetiteTitle = document.getElementById("entry-title");
const appetiteFields = document.getElementById("entry-fields");
const appetiteCancel = document.getElementById("entry-cancel");
const appetiteSave = document.getElementById("entry-save");

const APPETITE_FIELDS = [
  { key: "statement", label: "Statement", error: "Statement" },
  { key: "portfolio_ale_limit", label: "Annual Loss Expectancy Appetite (¤)", error: "Portfolio ALE Limit", numeric: true },
  { key: "portfolio_var95_limit", label: "Value at Risk 95 Appetite (¤)", error: "Portfolio VaR95 Limit", numeric: true },
  { key: "scenario_ale_tolerance", label: "Scenario Annual Loss Expectancy Tolerance (¤)", error: "Scenario ALE Tolerance", numeric: true },
  { key: "annual_treatment_budget", label: "Annual Treatment Budget (¤)", error: "Annual Treatment Budget", numeric: true },
  { key: "approval_threshold", label: "Approval Threshold (¤)", error: "Approval Threshold", numeric: true },
  { key: "amortisation_years", label: "Amortisation Years", error: "Amortisation Years", numeric: true },
  { key: "updated_by", label: "Updated By", error: "Updated By" },
];

function money(value) {
  if (value == null || Number.isNaN(Number(value))) return "N/A";
  return `¤ ${Number(value).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function ratioText(value) {
  if (value == null || Number.isNaN(Number(value))) return "N/A";
  return Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function setStatus(message, type) {
  statusBox.hidden = false;
  statusBox.textContent = message;
  statusBox.className = `status ${type}`;
}

function panel(title, body, action) {
  const section = document.createElement("section");
  section.className = "panel register-panel";
  const bar = document.createElement("div");
  bar.className = "section-bar";
  const heading = document.createElement("h2");
  heading.textContent = title;
  bar.appendChild(heading);
  if (action) bar.appendChild(action);
  section.appendChild(bar);
  if (body) section.appendChild(body);
  main.appendChild(section);
  return section;
}

function formatTimestamp(value) {
  const parsed = value ? new Date(value) : null;
  if (!parsed || Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function toleranceLabel(item) {
  if (item.status === "Draft" || item.in_appetite_test === false) return "Excluded";
  if (item.above_tolerance == null) return "Not defined";
  return item.above_tolerance ? "Yes" : "No";
}

function limitText(limit, status) {
  if (limit == null) return "Not defined";
  if (status === "Within" || status === "Breached") return `${money(limit)} — ${status}`;
  return money(limit);
}

async function load() {
  const [registerResponse, treatmentResponse] = await Promise.all([
    fetch("/register?iterations=10000&seed=1"),
    fetch("/treatments?iterations=10000&seed=1"),
  ]);
  const register = await registerResponse.json();
  const treatments = await treatmentResponse.json();
  if (!registerResponse.ok || !treatmentResponse.ok) {
    setStatus(register.detail || treatments.detail || "The register could not be loaded.", "error");
    return;
  }
  render(register, treatments);
}

function render(register, treatments) {
  main.querySelectorAll(".register-panel, .page-note").forEach((node) => node.remove());
  renderAppetite(register);

  const table = document.createElement("table");
  table.className = "inventory-table";
  table.innerHTML = "<thead><tr><th>Scenario</th><th>Inherent</th><th>Current</th><th>Target</th><th>Above tolerance</th></tr></thead>";
  const body = document.createElement("tbody");
  (register.items || []).forEach((item) => {
    const row = document.createElement("tr");
    [item.scenario_id, money(item.inherent?.mean), money(item.current?.mean), money(item.target?.mean), toleranceLabel(item)].forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.appendChild(cell);
    });
    body.appendChild(row);
  });
  table.appendChild(body);
  panel("Risk register", table);

  const investment = document.createElement("div");
  const recommendation = treatments.recommendation || {};
  const summary = document.createElement("p");
  summary.textContent = `Recommended ${(recommendation.selected_control_ids || []).join(", ") || "none"}. Reduction ${money(recommendation.expected_reduction)} at annualised cost ${money(recommendation.total_annualised_cost)}.`;
  investment.appendChild(summary);
  const candidateTable = document.createElement("table");
  candidateTable.className = "inventory-table";
  candidateTable.innerHTML = "<thead><tr><th>Control</th><th>Annualised cost</th><th>Reduction</th><th>Benefit-Cost Ratio</th><th>Return on Security Investment</th><th>Net benefit</th></tr></thead>";
  const candidates = document.createElement("tbody");
  (treatments.candidates || []).forEach((item) => {
    const row = document.createElement("tr");
    [item.control_id, money(item.annualised_cost), money(item.standalone_reduction), ratioText(item.benefit_cost_ratio), ratioText(item.rosi), money(item.net_benefit)].forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.appendChild(cell);
    });
    candidates.appendChild(row);
  });
  candidateTable.appendChild(candidates);
  investment.appendChild(candidateTable);
  const unrankedItems = treatments.unranked || [];
  if (unrankedItems.length) {
    const unranked = document.createElement("p");
    unranked.textContent = unrankedItems.map((item) => `${item.control_id}: ${item.reason}`).join("; ");
    investment.appendChild(unranked);
  }
  if (unrankedItems.some((item) => item.reason === "cost unknown")) {
    const note = document.createElement("p");
    note.className = "cost-link";
    const link = document.createElement("a");
    link.href = "/control-catalog";
    link.textContent = "Control Catalog";
    note.append("Define cost in the ", link);
    investment.appendChild(note);
  }
  panel("Investment analysis", investment);

  const button = document.createElement("button");
  button.type = "button";
  button.textContent = "Generate Board report";
  button.addEventListener("click", () => generate(register));
  panel("Board report", null, button);

  const note = document.createElement("p");
  note.className = "page-note";
  note.textContent = `NOTE: ${register.independence_note || treatments.independence_note || INDEPENDENCE}`;
  main.appendChild(note);
}

function renderAppetite(register) {
  const appetite = register.appetite || {};
  const evaluation = register.evaluation || {};
  const row = document.createElement("div");
  row.className = "appetite-row";
  const details = document.createElement("div");
  details.className = "appetite-details";
  const ale = document.createElement("p");
  ale.textContent = `Annual Loss Expectancy Appetite: ${limitText(appetite.portfolio_ale_limit, evaluation.portfolio_ale?.status)}`;
  const var95 = document.createElement("p");
  var95.textContent = `Value at Risk 95 Appetite: ${limitText(appetite.portfolio_var95_limit, evaluation.portfolio_var_95?.status)}`;
  details.append(ale, var95);
  if (appetite.statement) {
    const statement = document.createElement("p");
    statement.className = "appetite-statement";
    statement.textContent = appetite.statement;
    details.appendChild(statement);
  }
  const exclusion = document.createElement("p");
  exclusion.className = "appetite-statement";
  exclusion.textContent = "Draft scenarios are excluded from the appetite test.";
  details.appendChild(exclusion);
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = "Define Appetite";
  button.addEventListener("click", () => openAppetite(appetite));
  const actions = document.createElement("div");
  actions.className = "appetite-actions";
  actions.appendChild(button);
  if (appetite.updated_at && appetite.updated_by) {
    const meta = document.createElement("p");
    meta.className = "appetite-meta";
    meta.textContent = `Last updated on ${formatTimestamp(appetite.updated_at)} by ${appetite.updated_by}.`;
    actions.appendChild(meta);
  }
  row.append(details, actions);
  panel("Risk Appetite", row);
}

function openAppetite(appetite) {
  appetiteTitle.textContent = "Define Appetite";
  appetiteFields.replaceChildren(
    ...APPETITE_FIELDS.map((field) => {
      const wrap = document.createElement("label");
      wrap.className = "field";
      wrap.append(field.label);
      const input = document.createElement("input");
      input.name = field.key;
      input.value = appetite[field.key] ?? "";
      if (field.numeric) input.inputMode = "decimal";
      const error = document.createElement("span");
      error.className = "field-error";
      error.dataset.error = field.error;
      error.hidden = true;
      wrap.append(input, error);
      return wrap;
    }),
  );
  appetiteModal.hidden = false;
}

function showAppetiteErrors(errors) {
  appetiteFields.querySelectorAll(".field-error").forEach((node) => {
    const message = errors[node.dataset.error];
    node.hidden = !message;
    node.textContent = message || "";
  });
}

function closeAppetite() {
  appetiteModal.hidden = true;
}

appetiteCancel.addEventListener("click", closeAppetite);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !appetiteModal.hidden) closeAppetite();
});

appetiteForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {};
  APPETITE_FIELDS.forEach((field) => {
    const value = appetiteForm.elements[field.key].value.trim();
    payload[field.key] = field.numeric ? value.replace(/,/g, "") : value;
  });
  appetiteSave.disabled = true;
  const response = await fetch("/appetite", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  appetiteSave.disabled = false;
  if (!response.ok || !data.ok) {
    showAppetiteErrors(data.errors || {});
    if (!data.errors) setStatus(data.error || data.detail || "The appetite could not be saved.", "error");
    return;
  }
  closeAppetite();
  await load();
  setStatus("Appetite updated.", "success");
});

async function generate() {
  const title = window.prompt("Report title", "Cyber risk board pack");
  const preparedBy = window.prompt("Prepared by", "");
  if (!title || !preparedBy) return;
  const preview = window.open("about:blank", "_blank");
  if (!preview) {
    setStatus("Allow pop-ups to open the PDF in a new tab.", "error");
    return;
  }
  setStatus("Generating the board report…", "success");
  const response = await fetch("/decisions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, prepared_by: preparedBy, iterations: 10000, seed: 1 }),
  });
  const record = await response.json();
  if (!response.ok) {
    preview.close();
    setStatus(record.detail || "The board report could not be generated.", "error");
    return;
  }
  renderBoardReport(record.report, preview);
  setStatus(`Decision record ${record.record_id} created.`, "success");
}

load().catch((error) => setStatus(error.message, "error"));
