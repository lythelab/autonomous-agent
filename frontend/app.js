const apiInput = document.getElementById("apiUrl");
const apiHint = document.getElementById("apiHint");
const goalInput = document.getElementById("goal");
const output = document.getElementById("stateOutput");
const outputTitle = document.getElementById("outputTitle");
const statusBadge = document.getElementById("statusBadge");
const viewBadge = document.getElementById("viewBadge");

const saveApiButton = document.getElementById("saveApi");
const setGoalButton = document.getElementById("setGoal");
const runCycleButton = document.getElementById("runCycle");
const runFiveButton = document.getElementById("runFive");
const refreshButton = document.getElementById("refresh");
const resetButton = document.getElementById("reset");
const showStateButton = document.getElementById("showState");
const showLogsButton = document.getElementById("showLogs");
const showBothButton = document.getElementById("showBoth");

const storedUrl = localStorage.getItem("agentApiUrl") || "";
apiInput.value = storedUrl;
apiHint.textContent = storedUrl
  ? `Saved: ${storedUrl}`
  : "Set your AWS EC2 API URL (for example: http://<EC2_PUBLIC_DNS>) and click Save.";

let selectedView = "state";

saveApiButton.addEventListener("click", () => {
  const value = apiInput.value.trim().replace(/\/$/, "");
  localStorage.setItem("agentApiUrl", value);
  apiHint.textContent = value ? `Saved: ${value}` : "Please enter an API URL.";
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
  const value = (localStorage.getItem("agentApiUrl") || "").trim();
  return value.replace(/\/$/, "");
}

async function get(path) {
  const baseUrl = getBaseUrl();
  if (!baseUrl) {
    throw new Error("Set API URL first");
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
    apiHint.textContent = "Set API URL first.";
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
  apiHint.textContent = "Set your AWS EC2 API URL and click Save.";
});
