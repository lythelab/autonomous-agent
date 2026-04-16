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

const BACKEND_API_URL = isVercelDeployment() ? "/api" : "http://13.206.89.38";

const backendApiUrl = normalizeBaseUrl(BACKEND_API_URL);

let selectedView = "state";
const MAX_PREVIEW_STRING_LENGTH = 300;
const MAX_PREVIEW_ARRAY_ITEMS = 12;
const MAX_PREVIEW_OBJECT_KEYS = 20;
const MAX_PREVIEW_DEPTH = 4;

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
  const latestOutputText = extractLatestOutput(state, view);

  if (latestOutput) {
    latestOutput.textContent = latestOutputText || "No output available yet.";
    outputBadge.textContent = latestOutputText ? "ready" : "none";
    outputBadge.className = `badge ${latestOutputText ? "completed" : "idle"}`;
  }

  if (view === "state" && state.goal !== undefined) {
    const stateInfo = {
      goal: state.goal,
      status: state.status,
      iterations: state.iterations,
      completed_steps: countItems(state.completed_steps),
      remaining_steps: countItems(state.remaining_steps),
      failure_count: state.failure_count,
    };
    displayText = JSON.stringify(compactForDisplay(stateInfo), null, 2);
  } else {
    displayText = JSON.stringify(compactForDisplay(state), null, 2);
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

function extractLatestOutput(state, view) {
  if (!state) {
    return "";
  }

  if (view === "both") {
    return extractLatestOutput(state.state || state.logs || state, "state") || extractLatestOutput(state.logs, "logs");
  }

  if (typeof state.last_output === "string" && state.last_output.trim()) {
    return compactForDisplay(state.last_output);
  }

  if (typeof state.last_result?.output === "string" && state.last_result.output.trim()) {
    return compactForDisplay(state.last_result.output);
  }

  if (view === "logs") {
    const recentEpisodes = Array.isArray(state.recent_episodes) ? state.recent_episodes : [];
    for (const episode of recentEpisodes) {
      const episodeValue = episode?.value || {};
      const candidate = episodeValue?.result?.output || episodeValue?.output || episodeValue?.last_output;
      if (typeof candidate === "string" && candidate.trim()) {
        return compactForDisplay(candidate);
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

function compactForDisplay(value, depth = 0) {
  if (value === null || value === undefined) {
    return value;
  }

  if (typeof value === "string") {
    if (value.length <= MAX_PREVIEW_STRING_LENGTH) {
      return value;
    }

    return `${value.slice(0, MAX_PREVIEW_STRING_LENGTH)}… (truncated)`;
  }

  if (typeof value !== "object") {
    return value;
  }

  if (depth >= MAX_PREVIEW_DEPTH) {
    if (Array.isArray(value)) {
      return `[${value.length} items]`;
    }

    const keys = Object.keys(value);
    if (keys.length === 0) {
      return "{}";
    }

    const previewKeys = keys.slice(0, 3);
    return `{ ${previewKeys.join(", ")}${keys.length > previewKeys.length ? ", ..." : ""} }`;
  }

  if (Array.isArray(value)) {
    const items = value.slice(0, MAX_PREVIEW_ARRAY_ITEMS).map((item) => compactForDisplay(item, depth + 1));
    if (value.length > MAX_PREVIEW_ARRAY_ITEMS) {
      items.push(`… (${value.length - MAX_PREVIEW_ARRAY_ITEMS} more items)`);
    }
    return items;
  }

  const entries = Object.entries(value);
  const compacted = {};

  for (const [key, entryValue] of entries.slice(0, MAX_PREVIEW_OBJECT_KEYS)) {
    compacted[key] = compactForDisplay(entryValue, depth + 1);
  }

  if (entries.length > MAX_PREVIEW_OBJECT_KEYS) {
    compacted["…"] = `${entries.length - MAX_PREVIEW_OBJECT_KEYS} more keys`;
  }

  return compacted;
}

setView(selectedView);
setBackendStatus();

refreshView().catch((error) => {
  output.textContent = JSON.stringify({ message: error.message }, null, 2);
  apiHint.textContent = `Backend request failed: ${error.message}`;
  backendBadge.textContent = "error";
  backendBadge.className = "badge failed";
});
