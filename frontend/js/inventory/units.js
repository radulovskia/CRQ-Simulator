const FIELD_ERRORS = {
  "OU ID": "error-ou-id",
  "Organisational Unit": "error-organisational-unit",
  "Primary Responsibilities": "error-primary-responsibilities",
  Oversight: "error-oversight",
  Headcount: "error-headcount",
  "Loaded Hourly Cost": "error-loaded-hourly-cost",
};

const entryModal = document.getElementById("entry-modal");
const entryForm = document.getElementById("entry-form");
const entryTitle = document.getElementById("entry-title");
let previousId = null;

const catalog = mountCatalog({
  endpoint: "/units",
  deleteKeys: ["ou_id"],
  loadError: "The organisational units could not be loaded.",
  reviewColumns: ["OU ID", "Organisational Unit", "Primary Responsibilities", "Oversight", "Headcount", "Loaded Hourly Cost"],
  exportKeys: ["ou_id", "organisational_unit", "primary_responsibilities", "oversight", "headcount", "loaded_hourly_cost"],
  fields: [
    { key: "ou_id" },
    { key: "organisational_unit" },
    { key: "primary_responsibilities" },
    { key: "oversight" },
    { key: "headcount", nullable: true },
    { key: "loaded_hourly_cost", nullable: true },
  ],
  onCreate: () => openForm(null),
  onEdit: (item) => openForm(item),
});

function formValues() {
  return {
    ou_id: document.getElementById("field-ou-id").value.trim(),
    organisational_unit: document.getElementById("field-organisational-unit").value.trim(),
    primary_responsibilities: document.getElementById("field-primary-responsibilities").value.trim(),
    oversight: document.getElementById("field-oversight").value.trim(),
    headcount: optionalNumber("field-headcount"),
    loaded_hourly_cost: optionalNumber("field-loaded-hourly-cost"),
  };
}

function optionalNumber(id) {
  const raw = document.getElementById(id).value.trim();
  return raw === "" ? null : Number(raw);
}

function openForm(item) {
  previousId = item?.ou_id ?? null;
  entryTitle.textContent = previousId ? "Edit organisational unit" : "Add organisational unit";
  document.getElementById("field-ou-id").value = item?.ou_id ?? "";
  document.getElementById("field-organisational-unit").value = item?.organisational_unit ?? "";
  document.getElementById("field-primary-responsibilities").value = item?.primary_responsibilities ?? "";
  document.getElementById("field-oversight").value = item?.oversight ?? "";
  document.getElementById("field-headcount").value = item?.headcount ?? "";
  document.getElementById("field-loaded-hourly-cost").value = item?.loaded_hourly_cost ?? "";
  showMappedErrors({}, FIELD_ERRORS);
  entryModal.hidden = false;
  document.getElementById("field-ou-id").focus();
}

function closeForm() {
  entryModal.hidden = true;
  previousId = null;
}

async function saveForm(event) {
  event.preventDefault();
  const values = formValues();
  const errors = {};
  if (!values.ou_id) errors["OU ID"] = "must not be empty";
  if (!values.organisational_unit) errors["Organisational Unit"] = "must not be empty";
  if (!values.primary_responsibilities) errors["Primary Responsibilities"] = "must not be empty";
  if (!values.oversight) errors.Oversight = "must not be empty";
  if (Object.keys(errors).length) {
    showMappedErrors(errors, FIELD_ERRORS);
    return;
  }
  const saveButton = document.getElementById("entry-save");
  saveButton.disabled = true;
  try {
    const response = await fetch("/units/entry", {
      method: previousId ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(previousId ? { previous_ou_id: previousId, ...values } : values),
    });
    const data = await response.json();
    if (!data.ok) {
      showMappedErrors(data.errors || {}, FIELD_ERRORS);
      if (data.error) catalog.setStatus(data.error, "error");
      return;
    }
    const wasEdit = previousId != null;
    closeForm();
    catalog.replaceItems(data.items, data.extracted_at, wasEdit ? "Organisational unit updated." : "Organisational unit added.");
  } catch (error) {
    catalog.setStatus(error.message || "The organisational unit could not be saved.", "error");
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
