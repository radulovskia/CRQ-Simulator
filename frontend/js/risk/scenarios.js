const basis = ["", "External", "Internal", "Expert", "Mixed"];
const number = (name, label, header = label) => ({ name, label, header, kind: "number" });

const catalog = mountCatalog({
  endpoint: "/scenarios",
  deleteKeys: ["scenario_id"],
  loadError: "The risk scenarios could not be loaded.",
  reviewColumns: [
    "Scenario ID", "Scenario", "Threat Actor ID", "Attack Vector ID", "Target Type", "Target ID", "Risk Owner OU ID",
    "Description", "Status", "TEF Min", "TEF Mode", "TEF Max", "TEF Basis",
    "Susceptibility Min", "Susceptibility Mode", "Susceptibility Max", "Susceptibility Basis",
    "Max Loss Events per Year", "Frequency Lambda",
    "Response Min", "Response Mode", "Response Max", "Replacement Min", "Replacement Mode", "Replacement Max",
    "Productivity Min", "Productivity Mode", "Productivity Max", "Secondary Loss Probability",
    "Fines Min", "Fines Mode", "Fines Max", "Reputation Min", "Reputation Mode", "Reputation Max",
    "Competitive Min", "Competitive Mode", "Competitive Max", "Magnitude Basis", "Magnitude Lambda",
    "Evidence", "Calibration Notes",
  ],
  exportKeys: [
    "scenario_id", "scenario", "threat_actor_id", "attack_vector_id", "target_type", "target_id", "risk_owner_ou_id",
    "description", "status", "tef_min", "tef_mode", "tef_max", "tef_basis",
    "susceptibility_min", "susceptibility_mode", "susceptibility_max", "susceptibility_basis",
    "max_events_per_year", "frequency_lambda",
    "response_min", "response_mode", "response_max", "replacement_min", "replacement_mode", "replacement_max",
    "productivity_min", "productivity_mode", "productivity_max", "secondary_loss_probability",
    "fines_min", "fines_mode", "fines_max", "reputation_min", "reputation_mode", "reputation_max",
    "competitive_min", "competitive_mode", "competitive_max", "magnitude_basis", "magnitude_lambda",
    "evidence", "calibration_notes",
  ],
  fields: [
    { key: "scenario_id", label: "Scenario" },
    { key: "scenario", label: "Name" },
    { key: "threat_actor", label: "Actor" },
    { key: "attack_vector", label: "Vector" },
    { key: "target_name", label: "Target" },
    { key: "status", label: "Status", options: ["Draft", "Reviewed", "Approved"] },
    { key: "inherent_loss", label: "Inherent", format: "money" },
    { key: "current_loss", label: "Current", format: "money" },
    { key: "target_loss", label: "Target", format: "money" },
  ],
  enrich: attachLosses,
  rowActions: [
    { label: "Suggest", onClick: (item) => suggest(item) },
    { label: "Simulate", onClick: (item) => simulate(item) },
  ],
  onCreate: () => form.open(null),
  onEdit: (item) => form.open(item),
});

const form = mountEntryForm({
  catalog,
  endpoint: "/scenarios/entry",
  idKey: "scenario_id",
  previousKey: "previous_scenario_id",
  addTitle: "Add risk scenario",
  editTitle: "Edit risk scenario",
  fields: [
    { name: "scenario_id", label: "Scenario ID", header: "Scenario ID" },
    { name: "scenario", label: "Scenario", header: "Scenario" },
    { name: "threat_actor_id", label: "Threat Actor ID", header: "Threat Actor ID", choices: { endpoint: "/actors", id: "actor_id", name: "threat_actor" } },
    { name: "attack_vector_id", label: "Attack Vector ID", header: "Attack Vector ID", choices: { endpoint: "/vectors", id: "vector_id", name: "attack_vector" } },
    { name: "target_type", label: "Target Type", header: "Target Type", options: ["Software System", "Business Process"] },
    {
      name: "target_id",
      label: "Target ID",
      header: "Target ID",
      choices: {
        dependsOn: "target_type",
        async load(current) {
          if (current.target_type === "Software System") return catalogOptions("/systems", "system_id", "software_system");
          if (current.target_type === "Business Process") return catalogOptions("/processes", "bp_id", "business_process");
          return [];
        },
      },
    },
    { name: "risk_owner_ou_id", label: "Risk Owner Organisational Unit ID", header: "Risk Owner OU ID", choices: { endpoint: "/units", id: "ou_id", name: "organisational_unit" } },
    { name: "description", label: "Description", header: "Description" },
    { name: "status", label: "Status", header: "Status", options: ["", "Draft", "Reviewed", "Approved"] },
    number("tef_min", "Threat Event Frequency Min", "TEF Min"), number("tef_mode", "Threat Event Frequency Mode", "TEF Mode"), number("tef_max", "Threat Event Frequency Max", "TEF Max"),
    { name: "tef_basis", label: "Threat Event Frequency Basis", header: "TEF Basis", options: basis },
    number("susceptibility_min", "Susceptibility Min"), number("susceptibility_mode", "Susceptibility Mode"), number("susceptibility_max", "Susceptibility Max"),
    { name: "susceptibility_basis", label: "Susceptibility Basis", header: "Susceptibility Basis", options: basis },
    number("max_events_per_year", "Max Loss Events per Year"),
    number("frequency_lambda", "Frequency Lambda"),
    number("response_min", "Response Min"), number("response_mode", "Response Mode"), number("response_max", "Response Max"),
    number("replacement_min", "Replacement Min"), number("replacement_mode", "Replacement Mode"), number("replacement_max", "Replacement Max"),
    number("productivity_min", "Productivity Min"), number("productivity_mode", "Productivity Mode"), number("productivity_max", "Productivity Max"),
    number("secondary_loss_probability", "Secondary Loss Probability"),
    number("fines_min", "Fines Min"), number("fines_mode", "Fines Mode"), number("fines_max", "Fines Max"),
    number("reputation_min", "Reputation Min"), number("reputation_mode", "Reputation Mode"), number("reputation_max", "Reputation Max"),
    number("competitive_min", "Competitive Min"), number("competitive_mode", "Competitive Mode"), number("competitive_max", "Competitive Max"),
    { name: "magnitude_basis", label: "Magnitude Basis", header: "Magnitude Basis", options: basis },
    number("magnitude_lambda", "Magnitude Lambda"),
    { name: "evidence", label: "Evidence", header: "Evidence" },
    { name: "calibration_notes", label: "Calibration Notes", header: "Calibration Notes" },
  ],
});

async function attachLosses(items) {
  const response = await fetch("/register?iterations=10000&seed=1");
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || "The scenario results could not be loaded.");
  }
  const byId = new Map((data.items || []).map((item) => [item.scenario_id, item]));
  return items.map((item) => {
    const result = byId.get(item.scenario_id);
    return {
      ...item,
      inherent_loss: result?.inherent?.mean ?? null,
      current_loss: result?.current?.mean ?? null,
      target_loss: result?.target?.mean ?? null,
    };
  });
}

const suggestionHost = document.getElementById("suggestions");
const suggestionTitle = document.getElementById("suggestion-title");
const suggestionBody = document.getElementById("suggestion-body");

function fillFromSuggestion(name, suggestion) {
  if (!suggestion?.available) return;
  const input = document.getElementById(`field-${name}`);
  if (input && suggestion.value != null) input.value = suggestion.value;
  if (suggestion.minimum == null) return;
  const prefix = name.replace(/_(min|mode|max)$/, "");
  const min = document.getElementById(`field-${prefix}_min`);
  const mode = document.getElementById(`field-${prefix}_mode`);
  const max = document.getElementById(`field-${prefix}_max`);
  if (min) min.value = suggestion.minimum;
  if (mode) mode.value = suggestion.mode;
  if (max) max.value = suggestion.maximum;
}

async function suggest(item) {
  const params = new URLSearchParams({
    threat_actor_id: item.threat_actor_id,
    attack_vector_id: item.attack_vector_id,
    target_type: item.target_type,
    target_id: item.target_id,
  });
  const response = await fetch(`/scenarios/suggest?${params}`);
  const data = await response.json();
  if (!response.ok) {
    catalog.setStatus(data.detail || "Suggestions are unavailable.", "error");
    return;
  }
  const opened = await form.open(item);
  if (!opened) return;
  const suggestionLabels = {
    tef: "Threat Event Frequency",
    susceptibility: "Susceptibility",
    max_events_per_year: "Max Loss Events per Year",
    frequency_lambda: "Frequency Lambda",
    response: "Response",
    replacement: "Replacement",
    productivity: "Productivity",
    secondary_loss_probability: "Secondary Loss Probability",
    fines: "Fines",
    reputation: "Reputation",
    competitive: "Competitive",
    magnitude_lambda: "Magnitude Lambda",
  };
  suggestionBody.replaceChildren();
  Object.entries(suggestionLabels).forEach(([name, label]) => {
    const suggestion = data.suggestions[name];
    if (!suggestion) return;
    if (suggestion.available) fillFromSuggestion(name, suggestion);
    const row = document.createElement("tr");
    [label, proposalText(suggestion), reasonText(suggestion)].forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.appendChild(cell);
    });
    suggestionBody.appendChild(row);
  });
  suggestionTitle.textContent = `Proposals for ${item.scenario || item.scenario_id}`;
  suggestionHost.hidden = false;
}

function proposalText(suggestion) {
  if (!suggestion.available) return "Withheld";
  if (suggestion.minimum == null) {
    return Number(suggestion.value).toLocaleString(undefined, { maximumFractionDigits: 4 });
  }
  const format = (value) => Number(value).toLocaleString(undefined, { maximumFractionDigits: 4 });
  return [suggestion.minimum, suggestion.mode, suggestion.maximum].map(format).join(" / ");
}

function reasonText(suggestion) {
  if (!suggestion.available) return (suggestion.missing || []).join("; ") || "Insufficient data";
  return suggestion.rationale || "";
}

async function simulate(item) {
  const response = await fetch(`/scenarios/${item.scenario_id}/simulate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ control_set: "current", iterations: 10000, seed: 1 }),
  });
  const data = await response.json();
  if (!response.ok) {
    catalog.setStatus(data.detail || "The scenario could not be simulated.", "error");
    return;
  }
  sessionStorage.setItem("crqSimulationResult", JSON.stringify(data));
  window.location.assign("/result");
}
