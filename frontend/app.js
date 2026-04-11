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

const BACKEND_API_URL = isVercelDeployment() ? "/api" : "http://13.206.89.38";

const backendApiUrl = normalizeBaseUrl(BACKEND_API_URL);

let selectedView = "state";

checkHealthButton.addEventListener("click", checkBackendHealth);

reloadConfigButton.addEventListener("click", async () => {
  setBackendStatus();
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
  if (!backendApiUrl) {
    apiHint.textContent = "Backend URL is not configured. Set BACKEND_API_URL in frontend/app.js.";
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

function setBackendStatus() {
  if (backendApiUrl) {
    backendBadge.textContent = "ready";
    backendBadge.className = "badge completed";
    apiHint.textContent = `Using configured backend API URL: ${backendApiUrl}`;
    return;
  }

  backendBadge.textContent = "error";
  backendBadge.className = "badge failed";
  apiHint.textContent = "Backend URL is not configured. Set BACKEND_API_URL in frontend/app.js.";
  output.textContent = JSON.stringify({ message: "BACKEND_API_URL is empty" }, null, 2);
}

async function checkBackendHealth() {
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

function isVercelDeployment() {
  return window.location.hostname !== "localhost" && window.location.hostname !== "127.0.0.1";
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
  
  let displayText = "";
  const MAX_LENGTH = 3000;
  
  if (view === "state" && state.goal !== undefined) {
    const stateInfo = {
      goal: state.goal,
      status: state.status,
      iterations: state.iterations,
      completed_steps: state.completed_steps?.length || 0,
      remaining_steps: state.remaining_steps?.length || 0,
      failure_count: state.failure_count,
    };
    if (state.last_result?.output) {
      stateInfo.last_output = state.last_result.output.substring(0, 500);
    }
    displayText = JSON.stringify(stateInfo, null, 2);
  } else {
    displayText = JSON.stringify(state, null, 2);
  }
  
  if (displayText.length > MAX_LENGTH) {
    displayText = displayText.substring(0, MAX_LENGTH) + "\n\n... (output truncated)";
  }
  
  output.textContent = displayText;
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
setBackendStatus();

refreshView().catch((error) => {
  output.textContent = JSON.stringify({ message: error.message }, null, 2);
  apiHint.textContent = `Backend request failed: ${error.message}`;
  backendBadge.textContent = "error";
  backendBadge.className = "badge failed";
});
