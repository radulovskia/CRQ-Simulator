const API_BASE_URL = window.API_BASE_URL || "";
const SIMULATION_RESULT_KEY = "crqSimulationResult";

const form = document.getElementById("simulation-form");
const runButton = document.getElementById("run-button");
const statusBox = document.getElementById("status");

function parseOptionalInt(value) {
  if (value === "") {
    return null;
  }
  const parsed = Number.parseInt(value, 10);
  return Number.isNaN(parsed) ? null : parsed;
}

function parseConfidenceLevel(value, label) {
  const parsed = Number(value);
  if (Number.isNaN(parsed)) {
    throw new Error(`${label} confidence level must be a number between 1 and 10.`);
  }
  if (parsed < 1 || parsed > 10) {
    throw new Error(`${label} confidence level must be between 1 and 10.`);
  }
  return parsed;
}

function setStatus(message, type = "success") {
  statusBox.hidden = false;
  statusBox.textContent = message;
  statusBox.className = `status ${type}`;
}

function clearStatus() {
  statusBox.hidden = true;
  statusBox.textContent = "";
  statusBox.className = "status";
}

function formatApiError(payload, statusCode) {
  if (!payload) {
    return `Request failed with status ${statusCode}.`;
  }

  if (typeof payload.detail === "string") {
    return payload.detail;
  }

  if (Array.isArray(payload.detail)) {
    return payload.detail
      .map((item) => item.msg || JSON.stringify(item))
      .join(" ");
  }

  return `Request failed with status ${statusCode}.`;
}

const scenarioSelect = document.getElementById("scenario_id");
const controlSet = document.getElementById("control_set");

async function loadScenarios() {
  if (!scenarioSelect) return;
  const response = await fetch("/scenarios");
  if (!response.ok) return;
  const data = await response.json();
  (data.items || []).forEach((item) => {
    const option = document.createElement("option");
    option.value = item.scenario_id;
    option.textContent = `${item.scenario_id} — ${item.scenario}`;
    scenarioSelect.appendChild(option);
  });
}

async function applyScenario() {
  if (!scenarioSelect?.value) return;
  const response = await fetch(`/scenarios/${scenarioSelect.value}/inputs?control_set=${controlSet.value}`);
  const data = await response.json();
  if (!response.ok) {
    setStatus(data.detail || "The scenario inputs could not be loaded.", "error");
    return;
  }
  document.getElementById("frequency_minimum").value = data.frequency.minimum;
  document.getElementById("frequency_mode").value = data.frequency.mode;
  document.getElementById("frequency_maximum").value = data.frequency.maximum;
  document.getElementById("frequency_lambda").value = data.frequency.lambda;
  document.getElementById("magnitude_minimum").value = data.magnitude.minimum;
  document.getElementById("magnitude_mode").value = data.magnitude.mode;
  document.getElementById("magnitude_maximum").value = data.magnitude.maximum;
  document.getElementById("magnitude_lambda").value = data.magnitude.lambda;
  clearStatus();
}

scenarioSelect?.addEventListener("change", applyScenario);
controlSet?.addEventListener("change", applyScenario);
loadScenarios();

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearStatus();

  const formData = new FormData(form);

  try {
    const payload = {
      frequency: {
        minimum: Number(formData.get("frequency_minimum")),
        mode: Number(formData.get("frequency_mode")),
        maximum: Number(formData.get("frequency_maximum")),
        lambda_param: parseConfidenceLevel(formData.get("frequency_lambda"), "Frequency"),
      },
      magnitude: {
        minimum: Number(formData.get("magnitude_minimum")),
        mode: Number(formData.get("magnitude_mode")),
        maximum: Number(formData.get("magnitude_maximum")),
        lambda_param: parseConfidenceLevel(formData.get("magnitude_lambda"), "Magnitude"),
      },
      iterations: Number.parseInt(formData.get("iterations"), 10),
    };

    const seed = parseOptionalInt(formData.get("seed"));
    if (seed !== null) {
      payload.seed = seed;
    }

    runButton.disabled = true;
    runButton.textContent = "Running...";

    const response = await fetch(`${API_BASE_URL}/mc`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(formatApiError(data, response.status));
    }

    sessionStorage.setItem(SIMULATION_RESULT_KEY, JSON.stringify(data));
    window.location.assign("/result");
  } catch (error) {
    setStatus(error.message || "Simulation failed.", "error");
    runButton.disabled = false;
    runButton.textContent = "Run Simulation";
  }
});
