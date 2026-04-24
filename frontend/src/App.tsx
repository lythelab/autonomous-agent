import { FormEvent, useEffect, useMemo, useState } from "react";
import { askSessionQuestion, getLogs, getOutput, getStatus, getSystemLogs, startAgent, stopAgent } from "./api";

type UiState = "idle" | "running" | "stopping" | "completed" | "failed";

function statusToUi(status: string | undefined): UiState {
  if (!status) return "idle";
  if (status === "running") return "running";
  if (status === "stopped" || status === "stopping") return "stopping";
  if (status === "completed") return "completed";
  if (status.startsWith("failed")) return "failed";
  return "idle";
}

export default function App() {
  const [goal, setGoal] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [runtimeStatus, setRuntimeStatus] = useState<string>("idle");
  const [iteration, setIteration] = useState<number>(0);
  const [outputs, setOutputs] = useState<string[]>([]);
  const [logs, setLogs] = useState<Array<{ level: string; message: string; created_at: string; iteration: number }>>([]);
  const [systemLogs, setSystemLogs] = useState<Array<{ level: string; source: string; message: string; request_id: string; created_at: string }>>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatMessages, setChatMessages] = useState<Array<{ role: "user" | "assistant"; text: string }>>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const uiState = useMemo(() => statusToUi(runtimeStatus), [runtimeStatus]);

  useEffect(() => {
    if (!sessionId) return;

    let alive = true;
    const poll = async () => {
      try {
        const [statusRes, outputRes, logsRes] = await Promise.all([
          getStatus(sessionId),
          getOutput(sessionId, 200),
          getLogs(sessionId, 300),
        ]);

        if (!alive) return;
        if (statusRes.session) {
          setRuntimeStatus(statusRes.session.status);
          setIteration(statusRes.session.iteration);
          if (statusRes.session.goal && !goal) {
            setGoal(statusRes.session.goal);
          }
        }

        setOutputs(outputRes.outputs.filter((line) => line.trim().length > 0));
        setLogs(logsRes.logs);
      } catch (pollError) {
        if (!alive) return;
        setError(pollError instanceof Error ? pollError.message : "Polling failed");
      }
    };

    void poll();
    const interval = window.setInterval(() => {
      void poll();
    }, 2500);

    return () => {
      alive = false;
      window.clearInterval(interval);
    };
  }, [sessionId, goal]);

  useEffect(() => {
    let alive = true;

    const pollSystemLogs = async () => {
      try {
        const response = await getSystemLogs(300);
        if (!alive) return;
        setSystemLogs(response.logs);
      } catch (pollError) {
        if (!alive) return;
        setError(pollError instanceof Error ? pollError.message : "System log polling failed");
      }
    };

    void pollSystemLogs();
    const interval = window.setInterval(() => {
      void pollSystemLogs();
    }, 3000);

    return () => {
      alive = false;
      window.clearInterval(interval);
    };
  }, []);

  const onStart = async (event: FormEvent) => {
    event.preventDefault();
    setError("");

    const trimmedGoal = goal.trim();
    if (!trimmedGoal) {
      setError("Goal is required.");
      return;
    }

    setLoading(true);
    try {
      const response = await startAgent(trimmedGoal, sessionId || undefined);
      setSessionId(response.session_id);
      setRuntimeStatus(response.status);
    } catch (startError) {
      setError(startError instanceof Error ? startError.message : "Failed to start agent");
    } finally {
      setLoading(false);
    }
  };

  const onStop = async () => {
    setLoading(true);
    setError("");
    try {
      const response = await stopAgent();
      setRuntimeStatus(response.status);
    } catch (stopError) {
      setError(stopError instanceof Error ? stopError.message : "Failed to stop agent");
    } finally {
      setLoading(false);
    }
  };

  const onAsk = async (event: FormEvent) => {
    event.preventDefault();
    if (!sessionId) {
      setError("Start a session first, then ask chat questions.");
      return;
    }

    const question = chatInput.trim();
    if (!question) {
      return;
    }

    setError("");
    setChatLoading(true);
    setChatMessages((prev) => [...prev, { role: "user", text: question }]);
    setChatInput("");

    try {
      const response = await askSessionQuestion(sessionId, question);
      setChatMessages((prev) => [...prev, { role: "assistant", text: response.answer }]);
    } catch (chatError) {
      const message = chatError instanceof Error ? chatError.message : "Chat request failed";
      setError(message);
      setChatMessages((prev) => [...prev, { role: "assistant", text: `Chat failed: ${message}` }]);
    } finally {
      setChatLoading(false);
    }
  };

  return (
    <div className="page-shell">
      <div className="halo halo-left" />
      <div className="halo halo-right" />

      <header className="hero">
        <p className="kicker">Project 4</p>
        <h1>Autonomous Agent Console</h1>
        <p className="subtitle">
          Launch long-running goals, track progress over time, and view only the actual computation outputs.
        </p>
      </header>

      <main className="layout">
        <section className="card control-card">
          <h2>Control Plane</h2>
          <form onSubmit={onStart} className="control-form">
            <label htmlFor="goal">Goal</label>
            <textarea
              id="goal"
              value={goal}
              onChange={(event) => setGoal(event.target.value)}
              placeholder="Example: Analyze top AI trends and output a concise summary"
              rows={5}
            />

            <label htmlFor="sessionId">Session ID (optional resume)</label>
            <input
              id="sessionId"
              value={sessionId}
              onChange={(event) => setSessionId(event.target.value.trim())}
              placeholder="Leave empty for new session"
            />

            <div className="button-row">
              <button type="submit" className="primary" disabled={loading}>
                {loading ? "Working..." : "Start / Resume"}
              </button>
              <button
                type="button"
                className="ghost"
                onClick={onStop}
                disabled={loading || uiState !== "running"}
              >
                Stop
              </button>
            </div>
          </form>

          {error && <p className="error">{error}</p>}
        </section>

        <section className="card status-card">
          <h2>Session Status</h2>
          <div className="status-grid">
            <div>
              <p className="meta-label">State</p>
              <p className={`status-pill ${uiState}`}>{runtimeStatus || "idle"}</p>
            </div>
            <div>
              <p className="meta-label">Iteration</p>
              <p className="meta-value">{iteration}</p>
            </div>
            <div className="full">
              <p className="meta-label">Session ID</p>
              <p className="session-id">{sessionId || "None"}</p>
            </div>
          </div>
        </section>

        <section className="card output-card">
          <div className="output-header">
            <h2>Computation Output Stream</h2>
            <span className="count-chip">{outputs.length} entries</span>
          </div>

          <div className="output-list" aria-live="polite">
            {outputs.length === 0 ? (
              <p className="empty">No output yet. Start the agent to stream computation results.</p>
            ) : (
              outputs.map((line, idx) => (
                <pre key={`${idx}-${line.slice(0, 12)}`} className="output-line">
                  {line}
                </pre>
              ))
            )}
          </div>
        </section>

        <section className="card chat-card">
          <div className="output-header">
            <h2>Session Chatbot</h2>
            <span className="count-chip">{chatMessages.length} messages</span>
          </div>

          <div className="chat-list" aria-live="polite">
            {chatMessages.length === 0 ? (
              <p className="empty">Ask questions about this session's outputs and logs.</p>
            ) : (
              chatMessages.map((message, idx) => (
                <div key={`${idx}-${message.role}`} className={`chat-msg ${message.role}`}>
                  <p className="chat-role">{message.role === "user" ? "You" : "Agent"}</p>
                  <p className="chat-text">{message.text}</p>
                </div>
              ))
            )}
          </div>

          <form className="chat-form" onSubmit={onAsk}>
            <input
              value={chatInput}
              onChange={(event) => setChatInput(event.target.value)}
              placeholder="Ask about the outputs, failures, or conclusions"
            />
            <button type="submit" className="primary" disabled={chatLoading || !sessionId}>
              {chatLoading ? "Thinking..." : "Ask"}
            </button>
          </form>
        </section>

        <section className="card logs-card">
          <div className="output-header">
            <h2>Agent Runtime Logs</h2>
            <span className="count-chip">{logs.length} events</span>
          </div>
          <div className="output-list" aria-live="polite">
            {logs.length === 0 ? (
              <p className="empty">No logs yet. Start the agent to see planning and execution events.</p>
            ) : (
              logs.map((entry, idx) => (
                <div key={`${idx}-${entry.created_at}`} className="log-line">
                  <p className={`log-level ${entry.level.toLowerCase()}`}>{entry.level}</p>
                  <p className="log-message">{entry.message}</p>
                  <p className="log-meta">iter {entry.iteration} | {new Date(entry.created_at).toLocaleString()}</p>
                </div>
              ))
            )}
          </div>
        </section>

        <section className="card logs-card">
          <div className="output-header">
            <h2>System and API Logs</h2>
            <span className="count-chip">{systemLogs.length} events</span>
          </div>
          <div className="output-list" aria-live="polite">
            {systemLogs.length === 0 ? (
              <p className="empty">No system logs yet.</p>
            ) : (
              systemLogs.map((entry, idx) => (
                <div key={`${idx}-${entry.created_at}`} className="log-line">
                  <p className={`log-level ${entry.level.toLowerCase()}`}>{entry.level}</p>
                  <p className="log-message">[{entry.source}] {entry.message}</p>
                  <p className="log-meta">
                    {new Date(entry.created_at).toLocaleString()} | request {entry.request_id || "n/a"}
                  </p>
                </div>
              ))
            )}
          </div>
        </section>
      </main>
    </div>
  );
}
