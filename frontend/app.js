const apiHint = document.getElementById("apiHint");
const goalInput = document.getElementById("goal");
const output = document.getElementById("stateOutput");
const outputTitle = document.getElementById("outputTitle");
const statusBadge = document.getElementById("statusBadge");
const viewBadge = document.getElementById("viewBadge");
const backendBadge = document.getElementById("backendBadge");

const setGoalButton = document.getElementById("setGoal");
const runCycleButton = document.getElementById("runCycle");
const runFiveButton = document.getElementById("runFive");
const refreshButton = document.getElementById("refresh");
const resetButton = document.getElementById("reset");
const showStateButton = document.getElementById("showState");
const showLogsButton = document.getElementById("showLogs");
const showBothButton = document.getElementById("showBoth");
const checkHealthButton = document.getElementById("checkHealth");
const reloadConfigButton = document.getElementById("reloadConfig");

let backendApiUrl = "";
let configLoaded = false;

let selectedView = "state";

checkHealthButton.addEventListener("click", checkBackendHealth);

reloadConfigButton.addEventListener("click", async () => {
  await loadBackendConfig(true);
});

setGoalButton.addEventListener("click", async () => {
  const goal = goalInput.value.trim();
  if (!goal) {
    apiHint.textContent = "Enter a goal first.";
    return;
  }
  await post("/goal", { goal });
  await refreshView();
});

runCycleButton.addEventListener("click", async () => {
  await post("/cycle", {});
  await refreshView();
});

runFiveButton.addEventListener("click", async () => {
  await post("/run", { max_cycles: 5 });
  await refreshView();
});

refreshButton.addEventListener("click", refreshView);

resetButton.addEventListener("click", async () => {
  await post("/reset", {});
  await refreshView();
});

showStateButton.addEventListener("click", async () => {
  setView("state");
  await refreshView();
});

showLogsButton.addEventListener("click", async () => {
  setView("logs");
  await refreshView();
});

showBothButton.addEventListener("click", async () => {
  setView("both");
  await refreshView();
});

function setView(view) {
  selectedView = view;
  viewBadge.textContent = view;
  showStateButton.classList.toggle("active", view === "state");
  showLogsButton.classList.toggle("active", view === "logs");
  showBothButton.classList.toggle("active", view === "both");
  outputTitle.textContent = view === "state" ? "Current State" : view === "logs" ? "Recent Logs" : "State + Logs";
}

async function refreshView() {
  if (!configLoaded) {
    await loadBackendConfig();
  }

  if (!backendApiUrl) {
    return;
  }

  if (selectedView === "logs") {
    const logs = await get("/logs");
    renderState(logs, "logs");
    return;
  }

  if (selectedView === "both") {
    const [state, logs] = await Promise.all([get("/state"), get("/logs")]);
    renderState({ state, logs }, "both");
    return;
  }

  const state = await get("/state");
  renderState(state, "state");
}

function getBaseUrl() {
  return backendApiUrl;
}

async function get(path) {
  const baseUrl = getBaseUrl();
  if (!baseUrl) {
    throw new Error("Backend URL is not configured.");
  }
  const response = await fetch(`${baseUrl}${path}`);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json();
}

async function post(path, payload) {
  const baseUrl = getBaseUrl();
  if (!baseUrl) {
    apiHint.textContent = "Backend URL is not configured.";
    return null;
  }

  const response = await fetch(`${baseUrl}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const details = await safeText(response);
    apiHint.textContent = `Request failed (${response.status}): ${details}`;
    return null;
  }

  return response.json();
}

async function loadBackendConfig(force = false) {
  if (configLoaded && !force) {
    return;
  }

  backendBadge.textContent = "loading";
  backendBadge.className = "badge";
  apiHint.textContent = "Loading backend URL from .env...";

  try {
    const response = await fetch("/env");
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const payload = await response.json();
    backendApiUrl = normalizeBaseUrl(payload.backend_api_url || "");
    configLoaded = true;

    if (backendApiUrl) {
      backendBadge.textContent = "ready";
      backendBadge.className = "badge completed";
      apiHint.textContent = `Loaded backend API URL from .env: ${backendApiUrl}`;
      return;
    }

    throw new Error("BACKEND_API_URL is empty");
  } catch (error) {
    backendApiUrl = "";
    configLoaded = true;
    backendBadge.textContent = "error";
    backendBadge.className = "badge failed";
    apiHint.textContent = "Could not load backend URL from /env. Verify BACKEND_API_URL in .env and serve the frontend from the same host.";
    output.textContent = JSON.stringify({ message: error.message }, null, 2);
  }
}

async function checkBackendHealth() {
  if (!configLoaded) {
    await loadBackendConfig();
  }

  if (!backendApiUrl) {
    apiHint.textContent = "Backend URL is not configured.";
    return;
  }

  backendBadge.textContent = "checking";
  backendBadge.className = "badge running";

  try {
    const response = await fetch(`${backendApiUrl}/health`);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const payload = await response.json();
    backendBadge.textContent = payload.status || "ok";
    backendBadge.className = "badge completed";
    apiHint.textContent = `Backend health check passed: ${payload.status || "ok"}`;
  } catch (error) {
    backendBadge.textContent = "down";
    backendBadge.className = "badge failed";
    apiHint.textContent = `Backend health check failed: ${error.message}`;
  }
}

function normalizeBaseUrl(value) {
  return value.trim().replace(/\/$/, "");
}

async function safeText(response) {
  try {
    return await response.text();
  } catch {
    return "unknown error";
  }
}

function renderState(state, view = "state") {
  if (!state) {
    return;
  }
  output.textContent = JSON.stringify(state, null, 2);
  let badgeText = state.status || "idle";
  let badgeClass = state.status || "idle";

  if (view === "logs") {
    badgeText = `logs ${state.count ?? 0}`;
    badgeClass = "completed";
  } else if (view === "both") {
    badgeText = "mixed";
    badgeClass = "running";
  }

  statusBadge.textContent = badgeText;
  statusBadge.className = `badge ${badgeClass}`;
}

setView(selectedView);

refreshView().catch((error) => {
  output.textContent = JSON.stringify({ message: error.message }, null, 2);
  apiHint.textContent = "Backend URL loading failed. Check BACKEND_API_URL in .env.";
});
