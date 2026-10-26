const FIELD_ERRORS = {
  "System ID": "error-system-id",
  "Software System": "error-software-system",
  "Primary Function": "error-primary-function",
  "Business Owner OU ID": "error-business-owner",
  "Technical Custodian OU ID": "error-technical-custodian",
  Criticality: "error-criticality",
  "Data Classification": "error-data-classification",
  Deployment: "error-deployment",
};

const entryModal = document.getElementById("entry-modal");
const entryForm = document.getElementById("entry-form");
const entryTitle = document.getElementById("entry-title");
const ownerSelect = document.getElementById("field-business-owner");
const custodianSelect = document.getElementById("field-technical-custodian");
let previousId = null;

const catalog = mountCatalog({
  endpoint: "/systems",
  loadError: "The software systems could not be loaded.",
  reviewColumns: [
    "System ID",
    "Software System",
    "Primary Function",
    "Business Owner OU ID",
    "Technical Custodian OU ID",
    "Criticality",
    "Data Classification",
    "Deployment",
  ],
  ranks: {
    criticality: { Low: 0, Medium: 1, High: 2 },
    data_classification: { Public: 0, Internal: 1, Confidential: 2 },
  },
  fields: [
    { key: "system_id" },
    { key: "software_system" },
    { key: "primary_function" },
    { key: "business_owner_ou" },
    { key: "technical_custodian_ou" },
    { key: "criticality" },
    { key: "data_classification" },
    { key: "deployment" },
  ],
  onCreate: () => openForm(null),
  onEdit: (item) => openForm(item),
});

async function loadUnits() {
  const response = await fetch("/units");
  if (!response.ok) {
    throw new Error("The organisational units could not be loaded.");
  }
  const data = await response.json();
  const options = (data.items ?? []).map((item) => ({
    value: item.ou_id,
    label: optionLabel(item.ou_id, item.organisational_unit),
  }));
  fillSelect(ownerSelect, options, "Select");
  fillSelect(custodianSelect, options, "Select");
}

async function openForm(item) {
  previousId = item?.system_id ?? null;
  entryTitle.textContent = previousId ? "Edit software system" : "Add software system";
  showMappedErrors({}, FIELD_ERRORS);
  try {
    await loadUnits();
  } catch (error) {
    catalog.setStatus(error.message, "error");
    return;
  }
  document.getElementById("field-system-id").value = item?.system_id ?? "";
  document.getElementById("field-software-system").value = item?.software_system ?? "";
  document.getElementById("field-primary-function").value = item?.primary_function ?? "";
  ownerSelect.value = item?.business_owner_ou_id ?? "";
  custodianSelect.value = item?.technical_custodian_ou_id ?? "";
  document.getElementById("field-criticality").value = item?.criticality ?? "";
  document.getElementById("field-data-classification").value = item?.data_classification ?? "";
  document.getElementById("field-deployment").value = item?.deployment ?? "";
  entryModal.hidden = false;
  document.getElementById("field-system-id").focus();
}

function closeForm() {
  entryModal.hidden = true;
  previousId = null;
}

function formValues() {
  return {
    system_id: document.getElementById("field-system-id").value.trim(),
    software_system: document.getElementById("field-software-system").value.trim(),
    primary_function: document.getElementById("field-primary-function").value.trim(),
    business_owner_ou_id: ownerSelect.value,
    technical_custodian_ou_id: custodianSelect.value,
    criticality: document.getElementById("field-criticality").value,
    data_classification: document.getElementById("field-data-classification").value,
    deployment: document.getElementById("field-deployment").value.trim(),
  };
}

async function saveForm(event) {
  event.preventDefault();
  const values = formValues();
  const errors = {};
  if (!values.system_id) errors["System ID"] = "must not be empty";
  if (!values.software_system) errors["Software System"] = "must not be empty";
  if (!values.primary_function) errors["Primary Function"] = "must not be empty";
  if (!values.business_owner_ou_id) errors["Business Owner OU ID"] = "must be an existing OU ID";
  if (!values.technical_custodian_ou_id) errors["Technical Custodian OU ID"] = "must be an existing OU ID";
  if (!["Low", "Medium", "High"].includes(values.criticality)) {
    errors.Criticality = 'must be "Low", "Medium", or "High"';
  }
  if (!["Public", "Internal", "Confidential"].includes(values.data_classification)) {
    errors["Data Classification"] = 'must be "Public", "Internal", or "Confidential"';
  }
  if (!values.deployment) errors.Deployment = "must not be empty";
  if (Object.keys(errors).length) {
    showMappedErrors(errors, FIELD_ERRORS);
    return;
  }
  const saveButton = document.getElementById("entry-save");
  saveButton.disabled = true;
  try {
    const response = await fetch("/systems/entry", {
      method: previousId ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(previousId ? { previous_system_id: previousId, ...values } : values),
    });
    const data = await response.json();
    if (!data.ok) {
      showMappedErrors(data.errors || {}, FIELD_ERRORS);
      if (data.error) catalog.setStatus(data.error, "error");
      return;
    }
    const wasEdit = previousId != null;
    closeForm();
    catalog.replaceItems(data.items, data.extracted_at, wasEdit ? "Software system updated." : "Software system added.");
  } catch (error) {
    catalog.setStatus(error.message || "The software system could not be saved.", "error");
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
