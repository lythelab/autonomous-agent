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

// const BACKEND_API_URL = isVercelDeployment() ? "/api" : "http://13.206.89.38";
const BACKEND_API_URL = "http://localhost:8000";


const backendApiUrl = normalizeBaseUrl(BACKEND_API_URL);

let selectedView = "state";
let currentRenderedText = "";

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
  if (!currentRenderedText.trim()) {
    apiHint.textContent = "Nothing available to copy yet.";
    return;
  }

  try {
    await navigator.clipboard.writeText(currentRenderedText);
    apiHint.textContent = "Visible text copied to clipboard.";
  } catch (error) {
    apiHint.textContent = `Copy failed: ${error.message}`;
  }
});

downloadVisibleButton.addEventListener("click", () => {
  if (!currentRenderedText.trim()) {
    apiHint.textContent = "Nothing available to download yet.";
    return;
  }

  const blob = new Blob([currentRenderedText], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
  anchor.href = url;
  anchor.download = `autonomous-agent-${selectedView}-${timestamp}.log`;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
  apiHint.textContent = "Visible text downloaded.";
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
    const logsText = await getText("/logs");
    renderState({ logsText }, "logs");
    return;
  }

  if (selectedView === "both") {
    const [state, logsText] = await Promise.all([get("/state"), getText("/logs")]);
    renderState({ state, logsText }, "both");
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

async function getText(path) {
  const baseUrl = getBaseUrl();
  if (!baseUrl) {
    throw new Error("Backend URL is not configured.");
  }
  const response = await fetch(`${baseUrl}${path}`);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.text();
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
  output.textContent = "BACKEND_API_URL is empty";
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

  const renderedText = formatMainOutput(state, view);
  currentRenderedText = renderedText;
  output.textContent = renderedText;

  const stateForStats = view === "both" ? state.state || {} : view === "state" ? state : {};
  renderStats(stateForStats);

  let badgeText = state.status || "idle";
  let badgeClass = state.status || "idle";

  if (view === "logs") {
    badgeText = `logs ${countItems((state.logsText || "").split("\n").filter(Boolean))}`;
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
  const latestBody = extractLatestOutputBody(state, view);
  return formatLatestReport(latestBody);
}

function extractLatestOutputBody(state, view) {
  if (!state) {
    return "";
  }

  if (view === "both") {
    return (
      extractLatestOutputBody(state.state || state, "state")
      || extractLatestOutputBody({ logsText: state.logsText || "" }, "logs")
    );
  }

  if (typeof state.last_output === "string" && state.last_output.trim()) {
    return state.last_output;
  }

  if (typeof state.last_result?.output === "string" && state.last_result.output.trim()) {
    return state.last_result.output;
  }

  if (view === "logs") {
    const logsText = typeof state.logsText === "string" ? state.logsText : "";
    const lines = logsText.split("\n").filter(Boolean);
    for (let i = lines.length - 1; i >= 0; i -= 1) {
      const line = lines[i];
      const match = line.match(/Tool called: ([^\s]+)/);
      if (match) {
        return `Last tool call: ${match[1]}`;
      }
    }
    return logsText || "No logs yet.";
  }

  return "";
}

function formatMainOutput(state, view) {
  if (view === "logs") {
    const logsText = typeof state.logsText === "string" ? normalizeTextBlock(state.logsText) : "";
    return logsText || "No logs available yet.";
  }

  if (view === "both") {
    const stateText = formatStateText(state.state || {});
    const logsText = typeof state.logsText === "string" ? normalizeTextBlock(state.logsText) : "";
    const combined = `${stateText}\n\n[logs]\n${logsText || "No logs available yet."}`;
    return combined;
  }

  return formatStateText(state);
}

function formatStateText(state) {
  if (!state || typeof state !== "object") {
    return "No state available yet.";
  }

  const goal = state.goal || "n/a";
  const status = state.status || "idle";
  const iterations = state.iterations ?? 0;
  const failures = state.failure_count ?? 0;
  const completed = countItems(state.completed_steps);
  const remaining = countItems(state.remaining_steps);
  const lastOutput = normalizeTextBlock(extractLatestOutputBody(state, "state")) || "No output available yet.";

  return [
    `Goal: ${goal}`,
    `Status: ${status}`,
    `Iterations: ${iterations}`,
    `Failures: ${failures}`,
    `Completed: ${completed}`,
    `Remaining: ${remaining}`,
    "",
    "Latest output:",
    lastOutput,
  ].join("\n");
}

function formatLatestReport(text) {
  const cleaned = normalizeTextBlock(text);
  if (!cleaned) {
    return "[report]\nNo output available yet.";
  }
  return `[report]\n${cleaned}`;
}

function normalizeTextBlock(value) {
  let text = String(value ?? "").trim();
  if (!text) {
    return "";
  }

  if (text.startsWith('"') && text.endsWith('"')) {
    try {
      const parsed = JSON.parse(text);
      if (typeof parsed === "string") {
        text = parsed;
      }
    } catch {
      // Keep original text when it is not a JSON string literal.
    }
  }

  text = text
    .replace(/\r\n/g, "\n")
    .replace(/\\r/g, "")
    .replace(/\\n/g, "\n")
    .replace(/\\t/g, "\t")
    .trim();

  while (/^\[report\]\s*/i.test(text)) {
    text = text.replace(/^\[report\]\s*/i, "").trimStart();
  }

  return text.trim();
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
  output.textContent = `Backend request failed: ${error.message}`;
  apiHint.textContent = `Backend request failed: ${error.message}`;
  backendBadge.textContent = "error";
  backendBadge.className = "badge failed";
});
