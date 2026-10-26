const catalog = mountCatalog({
  endpoint: "/actors",
  deleteKeys: ["actor_id"],
  loadError: "The threat actors could not be loaded.",
  reviewColumns: ["Actor ID", "Threat Actor", "Actor Type", "Motivation", "Capability", "Sector Targeting", "ATT&CK Group IDs", "Description", "Reference"],
  exportKeys: ["actor_id", "threat_actor", "actor_type", "motivation", "capability", "sector_targeting", "attack_group_ids", "description", "reference"],
  fields: [
    { key: "actor_id", label: "Actor ID" },
    { key: "threat_actor", label: "Threat Actor" },
    { key: "actor_type", label: "Actor Type", options: ["Cybercrime", "Nation-State", "Hacktivist", "Insider", "Supply Chain", "Opportunistic"] },
    { key: "motivation", label: "Motivation", options: ["Financial", "Espionage", "Disruption", "Ideological", "Grievance"] },
    { key: "capability", label: "Capability", options: ["Low", "Medium", "High"] },
    { key: "sector_targeting", label: "Sector Targeting", options: ["Low", "Medium", "High"] },
  ],
  onCreate: () => form.open(null),
  onEdit: (item) => form.open(item),
});

const form = mountEntryForm({
  catalog,
  endpoint: "/actors/entry",
  idKey: "actor_id",
  previousKey: "previous_actor_id",
  addTitle: "Add threat actor",
  editTitle: "Edit threat actor",
  fields: [
    { name: "actor_id", label: "Actor ID", header: "Actor ID" },
    { name: "threat_actor", label: "Threat Actor", header: "Threat Actor" },
    { name: "actor_type", label: "Actor Type", header: "Actor Type", options: ["", "Cybercrime", "Nation-State", "Hacktivist", "Insider", "Supply Chain", "Opportunistic"] },
    { name: "motivation", label: "Motivation", header: "Motivation", options: ["", "Financial", "Espionage", "Disruption", "Ideological", "Grievance"] },
    { name: "capability", label: "Capability", header: "Capability", options: ["", "Low", "Medium", "High"] },
    { name: "sector_targeting", label: "Sector Targeting", header: "Sector Targeting", options: ["", "Low", "Medium", "High"] },
    { name: "attack_group_ids", label: "ATT&CK Group IDs", header: "ATT&CK Group IDs" },
    { name: "description", label: "Description", header: "Description" },
    { name: "reference", label: "Reference", header: "Reference" },
  ],
});
