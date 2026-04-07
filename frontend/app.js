const apiInput = document.getElementById("apiUrl");
const apiHint = document.getElementById("apiHint");
const goalInput = document.getElementById("goal");
const output = document.getElementById("stateOutput");
const statusBadge = document.getElementById("statusBadge");

const saveApiButton = document.getElementById("saveApi");
const setGoalButton = document.getElementById("setGoal");
const runCycleButton = document.getElementById("runCycle");
const runFiveButton = document.getElementById("runFive");
const refreshButton = document.getElementById("refresh");
const resetButton = document.getElementById("reset");

const storedUrl = localStorage.getItem("agentApiUrl") || "";
apiInput.value = storedUrl;

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
  await refreshState();
});

runCycleButton.addEventListener("click", async () => {
  await post("/cycle", {});
  await refreshState();
});

runFiveButton.addEventListener("click", async () => {
  await post("/run", { max_cycles: 5 });
  await refreshState();
});

refreshButton.addEventListener("click", refreshState);

resetButton.addEventListener("click", async () => {
  await post("/reset", {});
  await refreshState();
});

async function refreshState() {
  const data = await get("/state");
  renderState(data);
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

function renderState(state) {
  if (!state) {
    return;
  }
  output.textContent = JSON.stringify(state, null, 2);
  const status = state.status || "idle";
  statusBadge.textContent = status;
  statusBadge.className = `badge ${status}`;
}

refreshState().catch((error) => {
  output.textContent = JSON.stringify({ message: error.message }, null, 2);
  apiHint.textContent = "Set your backend API URL and click Save.";
});
