const FIELD_ERRORS = {
  "BP ID": "error-bp-id",
  "OU ID": "error-ou",
  "Business Process": "error-business-process",
  "Activity/Scope": "error-activity-scope",
  "Primary System IDs": "error-systems",
  Criticality: "error-criticality",
  "Key Information": "error-key-information",
};

const entryModal = document.getElementById("entry-modal");
const entryForm = document.getElementById("entry-form");
const entryTitle = document.getElementById("entry-title");
const ouSelect = document.getElementById("field-ou");
const systemSelect = document.getElementById("field-systems");
let previousId = null;

const catalog = mountCatalog({
  endpoint: "/processes",
  loadError: "The business process catalog could not be loaded.",
  reviewColumns: ["BP ID", "OU ID", "Business Process", "Activity/Scope", "Primary System IDs", "Criticality", "Key Information"],
  ranks: { criticality: { Low: 0, Medium: 1, High: 2 } },
  fields: [
    { key: "bp_id" },
    { key: "organisational_unit" },
    { key: "business_process" },
    { key: "activity_scope" },
    { key: "software_systems" },
    { key: "criticality" },
    { key: "key_information" },
  ],
  onCreate: () => openForm(null),
  onEdit: (item) => openForm(item),
});

async function loadChoices() {
  const [unitsResponse, systemsResponse] = await Promise.all([fetch("/units"), fetch("/systems")]);
  if (!unitsResponse.ok || !systemsResponse.ok) {
    throw new Error("The organisational units or software systems could not be loaded.");
  }
  const units = await unitsResponse.json();
  const systems = await systemsResponse.json();
  fillSelect(
    ouSelect,
    (units.items ?? []).map((item) => ({ value: item.ou_id, label: optionLabel(item.ou_id, item.organisational_unit) })),
    "Select",
  );
  fillSelect(
    systemSelect,
    (systems.items ?? []).map((item) => ({ value: item.system_id, label: optionLabel(item.system_id, item.software_system) })),
  );
}

async function openForm(item) {
  previousId = item?.bp_id ?? null;
  entryTitle.textContent = previousId ? "Edit business process" : "Add business process";
  showMappedErrors({}, FIELD_ERRORS);
  try {
    await loadChoices();
  } catch (error) {
    catalog.setStatus(error.message, "error");
    return;
  }
  document.getElementById("field-bp-id").value = item?.bp_id ?? "";
  ouSelect.value = item?.ou_id ?? "";
  document.getElementById("field-business-process").value = item?.business_process ?? "";
  document.getElementById("field-activity-scope").value = item?.activity_scope ?? "";
  const selected = new Set((item?.primary_system_ids ?? "").split(",").map((value) => value.trim()).filter(Boolean));
  [...systemSelect.options].forEach((option) => {
    option.selected = selected.has(option.value);
  });
  document.getElementById("field-criticality").value = item?.criticality ?? "";
  document.getElementById("field-key-information").value = item?.key_information ?? "";
  entryModal.hidden = false;
  document.getElementById("field-bp-id").focus();
}

function closeForm() {
  entryModal.hidden = true;
  previousId = null;
}

function formValues() {
  return {
    bp_id: document.getElementById("field-bp-id").value.trim(),
    ou_id: ouSelect.value,
    business_process: document.getElementById("field-business-process").value.trim(),
    activity_scope: document.getElementById("field-activity-scope").value.trim(),
    primary_system_ids: selectedValues(systemSelect).join(", "),
    criticality: document.getElementById("field-criticality").value,
    key_information: document.getElementById("field-key-information").value.trim(),
  };
}

async function saveForm(event) {
  event.preventDefault();
  const values = formValues();
  const errors = {};
  if (!values.bp_id) errors["BP ID"] = "must not be empty";
  if (!values.ou_id) errors["OU ID"] = "must be an existing OU ID";
  if (!values.business_process) errors["Business Process"] = "must not be empty";
  if (!values.activity_scope) errors["Activity/Scope"] = "must not be empty";
  if (!values.primary_system_ids) errors["Primary System IDs"] = "must not be empty";
  if (!["Low", "Medium", "High"].includes(values.criticality)) {
    errors.Criticality = 'must be "Low", "Medium", or "High"';
  }
  if (!values.key_information) errors["Key Information"] = "must not be empty";
  if (Object.keys(errors).length) {
    showMappedErrors(errors, FIELD_ERRORS);
    return;
  }
  const saveButton = document.getElementById("entry-save");
  saveButton.disabled = true;
  try {
    const response = await fetch("/processes/entry", {
      method: previousId ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(previousId ? { previous_bp_id: previousId, ...values } : values),
    });
    const data = await response.json();
    if (!data.ok) {
      showMappedErrors(data.errors || {}, FIELD_ERRORS);
      if (data.error) catalog.setStatus(data.error, "error");
      return;
    }
    const wasEdit = previousId != null;
    closeForm();
    catalog.replaceItems(data.items, data.extracted_at, wasEdit ? "Business process updated." : "Business process added.");
  } catch (error) {
    catalog.setStatus(error.message || "The business process could not be saved.", "error");
  } finally {
    saveButton.disabled = false;
  }
}

document.getElementById("entry-cancel").addEventListener("click", closeForm);
entryForm.addEventListener("submit", saveForm);
entryModal.addEventListener("click", (event) => {
  if (event.target === entryModal) closeForm();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !entryModal.hidden) closeForm();
});
