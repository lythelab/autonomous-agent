const apiHint = document.getElementById("apiHint");
const goalInput = document.getElementById("goal");
const latestOutput = document.getElementById("latestOutput");
const outputBadge = document.getElementById("outputBadge");
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
const wrapToggle = document.getElementById("wrapToggle");
const copyVisibleButton = document.getElementById("copyVisible");
const downloadVisibleButton = document.getElementById("downloadVisible");
const statIterations = document.getElementById("statIterations");
const statFailures = document.getElementById("statFailures");
const statCompleted = document.getElementById("statCompleted");
const statRemaining = document.getElementById("statRemaining");

const BACKEND_API_URL = isVercelDeployment() ? "/api" : "http://13.206.89.38";

const backendApiUrl = normalizeBaseUrl(BACKEND_API_URL);

let selectedView = "state";
let currentRenderedPayload = null;

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

wrapToggle.addEventListener("change", () => {
  const shouldWrap = wrapToggle.checked;
  latestOutput.classList.toggle("wrap", shouldWrap);
  output.classList.toggle("wrap", shouldWrap);
});

copyVisibleButton.addEventListener("click", async () => {
  const payload = currentRenderedPayload;
  if (!payload) {
    apiHint.textContent = "Nothing available to copy yet.";
    return;
  }

  try {
    await navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
    apiHint.textContent = "Visible JSON copied to clipboard.";
  } catch (error) {
    apiHint.textContent = `Copy failed: ${error.message}`;
  }
});

downloadVisibleButton.addEventListener("click", () => {
  const payload = currentRenderedPayload;
  if (!payload) {
    apiHint.textContent = "Nothing available to download yet.";
    return;
  }

  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
  anchor.href = url;
  anchor.download = `autonomous-agent-${selectedView}-${timestamp}.json`;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
  apiHint.textContent = "Visible JSON downloaded.";
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

  const latestOutputText = extractLatestOutput(state, view);

  if (latestOutput) {
    latestOutput.textContent = latestOutputText || "No output available yet.";
    outputBadge.textContent = latestOutputText ? "ready" : "none";
    outputBadge.className = `badge ${latestOutputText ? "completed" : "idle"}`;
  }

  currentRenderedPayload = state;
  output.textContent = JSON.stringify(state, null, 2);

  const stateForStats = view === "both" ? state.state || {} : view === "state" ? state : {};
  renderStats(stateForStats);

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

function renderStats(state) {
  const hasState = state && typeof state === "object";
  statIterations.textContent = hasState ? String(state.iterations ?? "-") : "-";
  statFailures.textContent = hasState ? String(state.failure_count ?? "-") : "-";
  statCompleted.textContent = hasState ? String(countItems(state.completed_steps)) : "-";
  statRemaining.textContent = hasState ? String(countItems(state.remaining_steps)) : "-";
}

function extractLatestOutput(state, view) {
  if (!state) {
    return "";
  }

  if (view === "both") {
    return extractLatestOutput(state.state || state.logs || state, "state") || extractLatestOutput(state.logs, "logs");
  }

  if (typeof state.last_output === "string" && state.last_output.trim()) {
    return state.last_output;
  }

  if (typeof state.last_result?.output === "string" && state.last_result.output.trim()) {
    return state.last_result.output;
  }

  if (view === "logs") {
    const recentEpisodes = Array.isArray(state.recent_episodes) ? state.recent_episodes : [];
    for (const episode of recentEpisodes) {
      const episodeValue = episode?.value || {};
      const candidate = episodeValue?.result?.output || episodeValue?.output || episodeValue?.last_output;
      if (typeof candidate === "string" && candidate.trim()) {
        return candidate;
      }
    }
  }

  return "";
}

function countItems(value) {
  if (Array.isArray(value)) {
    return value.length;
  }

  if (typeof value === "number") {
    return value;
  }

  return 0;
}

setView(selectedView);
setBackendStatus();

refreshView().catch((error) => {
  output.textContent = JSON.stringify({ message: error.message }, null, 2);
  apiHint.textContent = `Backend request failed: ${error.message}`;
  backendBadge.textContent = "error";
  backendBadge.className = "badge failed";
});
