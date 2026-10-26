(() => {
  const form = document.getElementById("benchmark-form");
  const host = document.getElementById("benchmark-fields");
  const status = document.getElementById("status");
  const updatedBy = document.getElementById("updated-by");
  const updatedAt = document.getElementById("updated-at");
  const versionText = document.getElementById("benchmark-version");
  const saveButton = document.getElementById("save-button");
  const confirmModal = document.getElementById("confirm-modal");
  const confirmChanges = document.getElementById("confirm-changes");
  const confirmOk = document.getElementById("confirm-ok");
  const confirmCancel = document.getElementById("confirm-cancel");

  const losses = ["Availability", "Integrity", "Confidentiality", "Fraud"];
  const classes = ["Public", "Internal", "Confidential"];
  const criticalities = ["Low", "Medium", "High"];
  const bounds = ["Minimum", "Mode", "Maximum"];
  let baseline = null;

  const groups = [
    {
      title: "Sector targeting",
      formula: "Threat Event Frequency = base Threat Event Frequency × targeting × reachability",
      note: "Suggest multiplies the attack vector’s base threat-event frequency by the actor’s sector-targeting level. The result is withheld when the vector requires internet exposure and any affected system’s exposure is Unknown.",
      fields: [{
        path: "targeting_multiplier",
        label: "Sector targeting",
        kind: "levels",
        parts: criticalities,
        hint: "Low, Medium, or High is the actor’s sector targeting.",
      }],
    },
    {
      title: "Reachability, not internet exposed",
      formula: "Threat Event Frequency = base Threat Event Frequency × targeting × reachability",
      note: "This is the reachability term when the vector requires internet exposure and no affected system is internet facing. An exposed system uses 1.",
      fields: [{
        path: "reachability_unexposed",
        label: "Factor",
        kind: "number",
        hint: "Applied only to an unexposed target.",
      }],
    },
    {
      title: "Evidence factor",
      formula: "susceptibility = base susceptibility × factor",
      note: "Suggest scales the vector’s base susceptibility and keeps every bound at or below 1. A vector that does not require a vulnerability uses 1. Exploitation evidence is chosen ahead of the Common Vulnerability Scoring System.",
      fields: [
        {
          path: "evidence_factor.none",
          label: "No findings",
          kind: "number",
          hint: "The affected systems have no vulnerability findings.",
        },
        {
          kind: "row",
          label: "Common Vulnerability Scoring System",
          hint: "Used when there is no Exploit Prediction Scoring System of 0.1 or more and no Known Exploited Vulnerability finding.",
          items: [
            { path: "evidence_factor.low_cvss", label: "Below 7", hint: "Highest Common Vulnerability Scoring System score is under 7." },
            { path: "evidence_factor.high_cvss", label: "7 or higher", hint: "Highest Common Vulnerability Scoring System score is 7 or above." },
            { path: "evidence_factor.unknown_cvss", label: "Unknown", hint: "Findings exist and every Common Vulnerability Scoring System score is blank." },
          ],
        },
        {
          path: "evidence_factor.exploited",
          label: "Exploit Prediction Scoring System at least 0.1 or Known Exploited Vulnerability",
          kind: "number",
          hint: "Highest Exploit Prediction Scoring System score is at least 0.1, or a finding is in the Known Exploited Vulnerability catalog. This is chosen ahead of the Common Vulnerability Scoring System.",
        },
      ],
    },
    {
      title: "Annual event cap",
      formula: "Loss Event Frequency maximum = min(Threat Event Frequency maximum × susceptibility maximum, cap)",
      note: "Suggest stores this as the scenario’s maximum loss events per year. The loss-event frequency mode is kept at or below that maximum.",
      fields: [
        { path: "cap.Fraud", label: "Fraud", kind: "number", hint: "Every fraud scenario." },
        { path: "cap.Confidentiality", label: "Confidentiality", kind: "number", hint: "Every confidentiality scenario." },
        {
          path: "cap.Availability",
          label: "Availability",
          kind: "levels",
          parts: criticalities,
          hint: "The level is the highest process criticality. Withheld when no process is linked.",
        },
        {
          path: "cap.Integrity",
          label: "Integrity",
          kind: "levels",
          parts: criticalities,
          hint: "The level is the highest process criticality. Withheld when no process is linked.",
        },
      ],
    },
    {
      title: "Frequency lambda",
      formula: "mean = (minimum + λ × mode + maximum) / (λ + 2)",
      note: "Suggest copies λ onto the scenario. Loss-event frequency is drawn from this shape, and analytic annual loss uses the mean. A higher λ pulls the result toward the mode. Allowed range is 1 to 10.",
      fields: [{ path: "frequency_lambda", label: "Lambda", kind: "number", hint: "Shape of the loss-event frequency draw." }],
    },
    {
      title: "Magnitude lambda",
      formula: "mean = (minimum + λ × mode + maximum) / (λ + 2)",
      note: "Suggest copies λ onto the scenario. Each loss amount is drawn from this shape. Analytic annual loss is the frequency mean times this mean. A higher λ pulls the result toward the mode. Allowed range is 1 to 10.",
      fields: [{ path: "magnitude_lambda", label: "Lambda", kind: "number", hint: "Shape of each loss-amount draw." }],
    },
    {
      title: "Replacement fraction",
      formula: "replacement = total replacement cost × fraction",
      note: "Suggest multiplies the sum of the affected systems’ replacement costs by this minimum, mode, and maximum. Withheld when any replacement cost is unknown.",
      fields: losses.map((loss) => ({
        path: `replacement_fraction.${loss}`,
        label: loss,
        kind: "triple",
        hint: "Fraction of replacement cost for this loss type.",
      })),
    },
    {
      title: "Response cost",
      formula: "primary loss = response + replacement + productivity",
      note: "Suggest copies this triple in as the response cost, then adds it to the other primary losses.",
      fields: [
        ...["Availability", "Integrity", "Fraud"].map((loss) => ({
          path: `response.${loss}`,
          label: loss,
          kind: "triple",
          hint: "Response cost for this loss type.",
        })),
        ...classes.map((name) => ({
          path: `response.Confidentiality.${name}`,
          label: `Confidentiality, ${name}`,
          kind: "triple",
          hint: `Used when the highest data classification is ${name}. Withheld when there is no system.`,
        })),
      ],
    },
    {
      title: "Secondary-loss probability",
      formula: "magnitude = primary loss + probability × (fines + reputation + competitive)",
      note: "Suggest stores this probability. Each simulated event includes fines, reputation, and competitive loss with this chance.",
      fields: [
        {
          kind: "row",
          label: "Confidentiality",
          hint: "The value is the highest data classification. Withheld when there is no system.",
          items: classes.map((name) => ({
            path: `secondary_loss_probability.Confidentiality.${name}`,
            label: name,
            hint: `Highest classification is ${name}.`,
          })),
        },
        {
          kind: "row",
          label: "Availability",
          items: [
            {
              path: "secondary_loss_probability.Availability.exposed_high",
              label: "Exposed and high criticality",
              hint: "A process is High and a system is internet facing.",
            },
            {
              path: "secondary_loss_probability.Availability.other",
              label: "Otherwise",
              hint: "Every other availability case. Withheld when exposure is Unknown and none is Yes.",
            },
          ],
        },
        {
          path: "secondary_loss_probability.Integrity",
          label: "Integrity",
          kind: "number",
          hint: "Every integrity scenario.",
        },
        {
          path: "secondary_loss_probability.Fraud",
          label: "Fraud",
          kind: "number",
          hint: "Every fraud scenario.",
        },
      ],
    },
    {
      title: "Fine per record",
      formula: "fine = min(records held × rate, cap)",
      note: "Suggest uses this when the highest classification is Confidential, for an availability, integrity, or confidentiality loss. Fraud stays zero. Unknown records withhold the fine.",
      fields: [
        ...["Confidentiality", "Integrity", "Availability"].map((loss) => ({
          path: `fine_per_record.${loss}`,
          label: loss,
          kind: "triple",
          hint: "Per-record rate when the data is Confidential.",
        })),
        {
          path: "fine_per_record.Fraud",
          label: "Fraud",
          kind: "triple",
          hint: "Fraud fines stay zero.",
        },
        { path: "fine_cap", label: "Fine cap", kind: "number", hint: "Upper bound on each fine estimate." },
      ],
    },
    {
      title: "Reputation",
      formula: "reputation = benchmark for the highest process criticality\nIntegrity and Fraud: reputation = that triple / 2",
      note: "Suggest takes the triple for the highest process criticality. Integrity and Fraud then use half of it. With no linked process, reputation is withheld.",
      fields: criticalities.map((name) => ({
        path: `reputation.${name}`,
        label: name,
        kind: "triple",
        hint: `Used when the highest process criticality is ${name}.`,
      })),
    },
    {
      title: "Competitive advantage",
      formula: "competitive loss = this triple, or 0",
      note: "The triple is added inside the secondary loss. Suggest uses it for a confidentiality event whose actor motivation is Espionage or whose actor type is Insider. Every other case is zero.",
      fields: [{
        path: "competitive",
        label: "Competitive advantage",
        kind: "triple",
        hint: "In scope for confidentiality plus espionage or an insider.",
      }],
    },
  ];

  groups.forEach((group) => {
    const fieldset = document.createElement("fieldset");
    fieldset.className = "benchmark-group";
    const legend = document.createElement("legend");
    legend.textContent = group.title;
    const formula = document.createElement("p");
    formula.className = "benchmark-formula";
    formula.textContent = group.formula;
    const note = document.createElement("p");
    note.className = "benchmark-note";
    note.textContent = group.note;
    fieldset.append(legend, formula, note);
    group.fields.forEach((field) => {
      if (field.kind === "triple") fieldset.append(rowField(group, field, bounds, "index"));
      else if (field.kind === "levels") fieldset.append(rowField(group, field, field.parts, "part"));
      else if (field.kind === "row") fieldset.append(scalarRow(group, field));
      else fieldset.append(valueField(group, field));
    });
    host.append(fieldset);
  });

  function changeLabel(group, field, part) {
    const details = [];
    if (field.label && field.label !== group.title && field.label !== "Factor" && field.label !== "Lambda") {
      details.push(field.label);
    }
    if (part) details.push(part);
    return details.length ? `${group.title} (${details.join(", ")})` : group.title;
  }

  function valueField(group, field) {
    const label = document.createElement("label");
    label.className = "field";
    label.append(document.createTextNode(field.label));
    if (field.hint) label.append(hintLine(field.hint));
    const input = document.createElement("input");
    input.type = field.kind === "number" ? "number" : "text";
    if (field.kind === "number") input.step = "any";
    input.dataset.path = field.path;
    input.dataset.change = changeLabel(group, field);
    const error = document.createElement("span");
    error.className = "field-error";
    error.dataset.error = field.path;
    error.hidden = true;
    label.append(input, error);
    return label;
  }

  function rowField(group, field, parts, mode) {
    const wrap = document.createElement("div");
    wrap.className = "field";
    const name = document.createElement("span");
    name.textContent = field.label;
    const row = document.createElement("div");
    row.className = "triple-row";
    if (field.hint) wrap.append(name, hintLine(field.hint));
    else wrap.append(name);
    parts.forEach((part, index) => {
      const label = document.createElement("label");
      label.className = "triple-part";
      label.append(document.createTextNode(part));
      const input = document.createElement("input");
      input.type = "number";
      input.step = "any";
      input.dataset.path = field.path;
      input.dataset.change = changeLabel(group, field, part);
      if (mode === "index") input.dataset.bound = String(index);
      else input.dataset.part = part;
      label.append(input);
      row.append(label);
    });
    const error = document.createElement("span");
    error.className = "field-error";
    error.dataset.error = field.path;
    error.hidden = true;
    wrap.append(row, error);
    return wrap;
  }

  function hintLine(text) {
    const hint = document.createElement("span");
    hint.className = "field-hint";
    hint.textContent = text;
    return hint;
  }

  function scalarRow(group, field) {
    const wrap = document.createElement("div");
    wrap.className = "field";
    const name = document.createElement("span");
    name.textContent = field.label;
    const row = document.createElement("div");
    row.className = "triple-row";
    if (field.hint) wrap.append(name, hintLine(field.hint));
    else wrap.append(name);
    field.items.forEach((item) => {
      const label = document.createElement("label");
      label.className = "triple-part";
      label.append(document.createTextNode(item.label));
      const input = document.createElement("input");
      input.type = "number";
      input.step = "any";
      input.dataset.path = item.path;
      input.dataset.change = changeLabel(group, { label: field.label }, item.label);
      const error = document.createElement("span");
      error.className = "field-error";
      error.dataset.error = item.path;
      error.hidden = true;
      label.append(input, error);
      if (item.hint) label.append(hintLine(item.hint));
      row.append(label);
    });
    wrap.append(row);
    return wrap;
  }

  function readPath(source, path) {
    return path.split(".").reduce((value, key) => (value == null ? undefined : value[key]), source);
  }

  function writePath(target, path, value) {
    const parts = path.split(".");
    let cursor = target;
    parts.forEach((part, index) => {
      if (index === parts.length - 1) {
        cursor[part] = value;
        return;
      }
      if (!cursor[part] || typeof cursor[part] !== "object" || Array.isArray(cursor[part])) cursor[part] = {};
      cursor = cursor[part];
    });
  }

  function storedValue(input) {
    const value = readPath(baseline, input.dataset.path);
    if (input.dataset.part != null) return value?.[input.dataset.part];
    if (input.dataset.bound != null) return Array.isArray(value) ? value[Number(input.dataset.bound)] : undefined;
    return value;
  }

  function sameValue(stored, raw) {
    if (raw === "") return stored == null || stored === "";
    const next = Number(raw);
    if (Number.isNaN(next)) return String(stored ?? "") === raw;
    return Number(stored) === next;
  }

  function formatValue(value) {
    if (value == null || value === "") return "";
    const number = Number(value);
    return Number.isNaN(number) ? String(value) : number.toLocaleString(undefined, { maximumFractionDigits: 4 });
  }

  function modifications() {
    return [...host.querySelectorAll("input")].flatMap((input) => {
      const stored = storedValue(input);
      if (sameValue(stored, input.value)) return [];
      return [{ name: input.dataset.change, values: `${formatValue(stored)} -> ${formatValue(input.value)}` }];
    });
  }

  function fill(benchmarks) {
    baseline = benchmarks;
    host.querySelectorAll("input").forEach((input) => {
      const value = storedValue(input);
      input.value = value ?? "";
    });
  }

  function collect() {
    const benchmarks = {};
    host.querySelectorAll("input").forEach((input) => {
      const number = input.value === "" ? null : Number(input.value);
      if (input.dataset.part != null) {
        const current = readPath(benchmarks, input.dataset.path);
        const record = current && typeof current === "object" && !Array.isArray(current) ? current : {};
        record[input.dataset.part] = number;
        writePath(benchmarks, input.dataset.path, record);
        return;
      }
      if (input.dataset.bound != null) {
        const current = readPath(benchmarks, input.dataset.path);
        const triple = Array.isArray(current) ? current : [null, null, null];
        triple[Number(input.dataset.bound)] = number;
        writePath(benchmarks, input.dataset.path, triple);
        return;
      }
      writePath(benchmarks, input.dataset.path, input.type === "number" ? number : input.value.trim());
    });
    return benchmarks;
  }

  function showStatus(message, kind) {
    status.hidden = false;
    status.textContent = message;
    status.className = kind ? `status ${kind}` : "status";
  }

  function showErrors(errors) {
    document.querySelectorAll(".field-error").forEach((item) => {
      item.hidden = true;
      item.textContent = "";
    });
    Object.entries(errors || {}).forEach(([path, message]) => {
      const target = document.querySelector(`[data-error="${path}"]`)
        || document.querySelector(`[data-error="${path.split(".").slice(0, -1).join(".")}"]`);
      if (!target) return;
      target.hidden = false;
      target.textContent = message;
    });
  }

  function showRecord(payload) {
    versionText.textContent = payload.benchmarks?.version || "2026.10";
    updatedBy.value = payload.updated_by || "";
    if (!payload.saved || !payload.updated_at) {
      updatedAt.textContent = "Not yet saved";
      return;
    }
    updatedAt.textContent = new Date(payload.updated_at).toLocaleString();
  }

  function closeConfirm() {
    confirmModal.hidden = true;
    confirmChanges.replaceChildren();
  }

  function openConfirm(lines) {
    confirmChanges.replaceChildren(...lines.map((line) => {
      const item = document.createElement("li");
      const name = document.createElement("span");
      name.className = "change-name";
      name.textContent = line.name;
      const values = document.createElement("span");
      values.className = "change-values";
      values.textContent = line.values;
      item.append(name, values);
      return item;
    }));
    confirmModal.hidden = false;
    confirmOk.focus();
  }

  async function save() {
    saveButton.disabled = true;
    confirmOk.disabled = true;
    try {
      const response = await fetch("/benchmarks", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ updated_by: updatedBy.value.trim(), benchmarks: collect() }),
      });
      const payload = await response.json();
      if (!payload.ok) {
        showErrors(payload.errors);
        showStatus("Nothing was saved.", "error");
        return;
      }
      fill(payload.benchmarks);
      showRecord(payload);
      showStatus("Benchmarks saved.", "success");
    } catch (error) {
      showStatus("The benchmarks could not be saved.", "error");
    } finally {
      saveButton.disabled = false;
      confirmOk.disabled = false;
      closeConfirm();
    }
  }

  async function load() {
    const response = await fetch("/benchmarks");
    if (!response.ok) {
      showStatus("The benchmarks could not be loaded.", "error");
      return;
    }
    const payload = await response.json();
    fill(payload.benchmarks);
    showRecord(payload);
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    showErrors({});
    if (!baseline) {
      showStatus("The benchmarks are still loading.");
      return;
    }
    if (!updatedBy.value.trim()) {
      showErrors({ updated_by: "Last modified by cannot be empty" });
      return;
    }
    const lines = modifications();
    if (!lines.length) {
      showStatus("No modifications to save.");
      return;
    }
    openConfirm(lines);
  });

  confirmOk.addEventListener("click", () => save());
  confirmCancel.addEventListener("click", closeConfirm);
  confirmModal.addEventListener("click", (event) => {
    if (event.target === confirmModal) closeConfirm();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !confirmModal.hidden) closeConfirm();
  });

  load().catch(() => showStatus("The benchmarks could not be loaded.", "error"));
})();
