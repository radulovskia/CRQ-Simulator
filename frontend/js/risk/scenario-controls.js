const catalog = mountCatalog({
  endpoint: "/scenario-controls",
  deleteKeys: ["scenario_id", "control_id"],
  loadError: "The scenario-control mappings could not be loaded.",
  reviewColumns: ["Scenario ID", "Control ID", "Frequency Reduction Override (%)", "Magnitude Reduction Override (%)", "Eliminates Risk", "Rationale"],
  exportKeys: ["scenario_id", "control_id", "frequency_reduction_override_pct", "magnitude_reduction_override_pct", "eliminates_risk", "rationale"],
  fields: [
    { key: "scenario_id", label: "Scenario ID" },
    { key: "control_id", label: "Control ID" },
    { key: "effective_frequency_reduction_pct", label: "Frequency %" },
    { key: "effective_magnitude_reduction_pct", label: "Magnitude %" },
    { key: "eliminates_risk", label: "Eliminates Risk", options: ["Yes", "No"] },
    { key: "control_status", label: "Control Status", options: ["Implemented", "Planned", "Not Implemented"] },
  ],
  onCreate: () => form.open(null),
  onEdit: (item) => form.open(item),
});

const form = mountEntryForm({
  catalog,
  endpoint: "/scenario-controls/entry",
  idKey: "scenario_id",
  secondaryKey: "control_id",
  previousKey: "previous_scenario_id",
  previousSecondaryKey: "previous_control_id",
  addTitle: "Add scenario-control mapping",
  editTitle: "Edit scenario-control mapping",
  fields: [
    { name: "scenario_id", label: "Scenario ID", header: "Scenario ID", choices: { endpoint: "/scenarios", id: "scenario_id", name: "scenario" } },
    { name: "control_id", label: "Control ID", header: "Control ID", choices: { endpoint: "/controls", id: "control_id", name: "control" } },
    { name: "frequency_reduction_override_pct", label: "Frequency Reduction Override (%)", header: "Frequency Reduction Override (%)", kind: "number" },
    { name: "magnitude_reduction_override_pct", label: "Magnitude Reduction Override (%)", header: "Magnitude Reduction Override (%)", kind: "number" },
    { name: "eliminates_risk", label: "Eliminates Risk", header: "Eliminates Risk", options: ["No", "Yes"] },
    { name: "rationale", label: "Rationale", header: "Rationale" },
  ],
});
