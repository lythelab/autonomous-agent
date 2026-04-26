import { FormEvent, ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  askSessionQuestion,
  getLogs,
  getOutput,
  getStatus,
  getSystemLogs,
  LogEntry,
  startAgent,
  stopAgent,
  SystemLogEntry,
} from "./api";

type UiState = "idle" | "running" | "stopping" | "completed" | "failed";
type MessageRole = "user" | "assistant";

type SessionRecord = {
  sessionId: string;
  goal: string;
  status: string;
  iteration: number;
  updatedAt: string;
};

type ChatMessage = {
  id: string;
  role: MessageRole;
  text: string;
};

type ActionEvent = {
  id: string;
  summary: string;
  detail: string;
  toolCall: string;
  result: string;
  createdAt: string;
};

const SESSIONS_STORAGE_KEY = "autonomous-agent-session-history";

function statusToUi(status: string | undefined): UiState {
  if (!status) return "idle";
  if (status === "running") return "running";
  if (status === "stopped" || status === "stopping") return "stopping";
  if (status === "completed") return "completed";
  if (status.startsWith("failed")) return "failed";
  return "idle";
}

function truncate(text: string, length: number): string {
  if (text.length <= length) return text;
  return `${text.slice(0, length - 1)}…`;
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) {
    return "now";
  }

  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function inferAction(entry: LogEntry): ActionEvent | null {
  const lowerMessage = entry.message.toLowerCase();
  const looksLikeAction =
    lowerMessage.includes("tool") ||
    lowerMessage.includes("search") ||
    lowerMessage.includes("execute") ||
    lowerMessage.includes("planning") ||
    lowerMessage.includes("iteration") ||
    lowerMessage.includes("web");

  if (!looksLikeAction) {
    return null;
  }

  return {
    id: `${entry.created_at}-${entry.iteration}-${entry.level}`,
    summary: truncate(entry.message, 72),
    detail: entry.message,
    toolCall: `${entry.level.toUpperCase()} @ iter ${entry.iteration}`,
    result: "Action recorded in runtime logs",
    createdAt: entry.created_at,
  };
}

function logLevelClass(level: string): "info" | "warn" | "error" {
  const normalized = level.toLowerCase();
  if (normalized.startsWith("error")) return "error";
  if (normalized.startsWith("warn")) return "warn";
  return "info";
}

function ThinkingDots(): ReactNode {
  return (
    <div className="thinking-row" aria-live="polite">
      <span className="thinking-label">Thinking</span>
      <div className="thinking-dots" aria-hidden="true">
        {[0, 1, 2].map((index) => (
          <motion.span
            key={index}
            className="thinking-dot"
            animate={{ opacity: [0.25, 1, 0.25], y: [0, -2, 0] }}
            transition={{ duration: 1.1, repeat: Number.POSITIVE_INFINITY, delay: index * 0.14 }}
          />
        ))}
      </div>
    </div>
  );
}

export default function App() {
  const [activeSessionId, setActiveSessionId] = useState("");
  const [runtimeStatus, setRuntimeStatus] = useState<string>("idle");
  const [iteration, setIteration] = useState<number>(0);
  const [outputs, setOutputs] = useState<string[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [systemLogs, setSystemLogs] = useState<SystemLogEntry[]>([]);
  const [error, setError] = useState("");

  const [chatInput, setChatInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [chatLoading, setChatLoading] = useState(false);
  const [sessionHistory, setSessionHistory] = useState<SessionRecord[]>([]);
  const [messagesBySession, setMessagesBySession] = useState<Record<string, ChatMessage[]>>({});
  const [expandedActions, setExpandedActions] = useState<Record<string, boolean>>({});
  const [systemLogsExpanded, setSystemLogsExpanded] = useState(false);

  const messageFeedRef = useRef<HTMLDivElement | null>(null);
  const runtimeLogsRef = useRef<HTMLDivElement | null>(null);

  const uiState = useMemo(() => statusToUi(runtimeStatus), [runtimeStatus]);

  useEffect(() => {
    const raw = window.localStorage.getItem(SESSIONS_STORAGE_KEY);
    if (!raw) return;

    try {
      const parsed = JSON.parse(raw) as SessionRecord[];
      if (Array.isArray(parsed)) {
        setSessionHistory(parsed);
      }
    } catch {
      window.localStorage.removeItem(SESSIONS_STORAGE_KEY);
    }
  }, []);

  useEffect(() => {
    window.localStorage.setItem(SESSIONS_STORAGE_KEY, JSON.stringify(sessionHistory));
  }, [sessionHistory]);

  useEffect(() => {
    if (!activeSessionId) {
      return;
    }

    let active = true;

    const poll = async () => {
      try {
        const [statusRes, outputRes, logsRes] = await Promise.all([
          getStatus(activeSessionId),
          getOutput(activeSessionId, 200),
          getLogs(activeSessionId, 300),
        ]);

        if (!active) {
          return;
        }

        if (statusRes.session) {
          const currentSession = statusRes.session;
          setRuntimeStatus(statusRes.session.status);
          setIteration(statusRes.session.iteration);

          setSessionHistory((previous) => {
            const withoutCurrent = previous.filter((item) => item.sessionId !== currentSession.session_id);
            const current: SessionRecord = {
              sessionId: currentSession.session_id,
              goal: currentSession.goal,
              status: currentSession.status,
              iteration: currentSession.iteration,
              updatedAt: currentSession.updated_at,
            };
            return [current, ...withoutCurrent].slice(0, 50);
          });
        }

        setOutputs(outputRes.outputs.filter((line) => line.trim().length > 0));
        setLogs(logsRes.logs);
      } catch (pollError) {
        if (!active) return;
        setError(pollError instanceof Error ? pollError.message : "Polling failed");
      }
    };

    void poll();
    const interval = window.setInterval(() => {
      void poll();
    }, 2500);

    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [activeSessionId]);

  useEffect(() => {
    let active = true;

    const pollSystemLogs = async () => {
      try {
        const response = await getSystemLogs(300);
        if (!active) {
          return;
        }
        setSystemLogs(response.logs);
      } catch (pollError) {
        if (!active) {
          return;
        }
        setError(pollError instanceof Error ? pollError.message : "System log polling failed");
      }
    };

    void pollSystemLogs();
    const interval = window.setInterval(() => {
      void pollSystemLogs();
    }, 3000);

    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    if (messageFeedRef.current) {
      messageFeedRef.current.scrollTop = messageFeedRef.current.scrollHeight;
    }
  }, [activeSessionId, messagesBySession, outputs, logs, chatLoading]);

  useEffect(() => {
    if (uiState === "running" && runtimeLogsRef.current) {
      runtimeLogsRef.current.scrollTop = runtimeLogsRef.current.scrollHeight;
    }
  }, [logs, uiState]);

  const activeMessages = useMemo(() => {
    if (!activeSessionId) {
      return [];
    }
    return messagesBySession[activeSessionId] ?? [];
  }, [activeSessionId, messagesBySession]);

  const actionEvents = useMemo(() => {
    return logs
      .map((entry) => inferAction(entry))
      .filter((item): item is ActionEvent => item !== null)
      .slice(-12);
  }, [logs]);

  const currentSession = useMemo(
    () => sessionHistory.find((session) => session.sessionId === activeSessionId) ?? null,
    [sessionHistory, activeSessionId],
  );

  const onNewSession = () => {
    setActiveSessionId("");
    setRuntimeStatus("idle");
    setIteration(0);
    setOutputs([]);
    setLogs([]);
    setError("");
    setChatInput("");
  };

  const updateSessionMessages = (sessionId: string, updater: (previous: ChatMessage[]) => ChatMessage[]) => {
    setMessagesBySession((previous) => {
      const next = { ...previous };
      next[sessionId] = updater(previous[sessionId] ?? []);
      return next;
    });
  };

  const onSubmitInput = async (event: FormEvent) => {
    event.preventDefault();
    const prompt = chatInput.trim();
    if (!prompt) {
      return;
    }

    setError("");

    if (!activeSessionId) {
      setBusy(true);
      try {
        const start = await startAgent(prompt);
        const newSessionId = start.session_id;
        setActiveSessionId(newSessionId);
        setRuntimeStatus(start.status);
        setIteration(0);

        setSessionHistory((previous) => {
          const withoutCurrent = previous.filter((item) => item.sessionId !== newSessionId);
          const current: SessionRecord = {
            sessionId: newSessionId,
            goal: prompt,
            status: start.status,
            iteration: 0,
            updatedAt: new Date().toISOString(),
          };
          return [current, ...withoutCurrent].slice(0, 50);
        });

        updateSessionMessages(newSessionId, () => [
          { id: `${Date.now()}-user-start`, role: "user", text: prompt },
          {
            id: `${Date.now()}-assistant-start`,
            role: "assistant",
            text: "Session started. I am running the goal and will stream progress in logs and outputs.",
          },
        ]);

        setChatInput("");
      } catch (startError) {
        setError(startError instanceof Error ? startError.message : "Failed to start agent");
      } finally {
        setBusy(false);
      }
      return;
    }

    const sessionId = activeSessionId;
    setChatLoading(true);
    updateSessionMessages(sessionId, (previous) => [
      ...previous,
      { id: `${Date.now()}-user`, role: "user", text: prompt },
    ]);
    setChatInput("");

    try {
      const response = await askSessionQuestion(sessionId, prompt);
      updateSessionMessages(sessionId, (previous) => [
        ...previous,
        { id: `${Date.now()}-assistant`, role: "assistant", text: response.answer },
      ]);
    } catch (chatError) {
      const message = chatError instanceof Error ? chatError.message : "Chat request failed";
      setError(message);
      updateSessionMessages(sessionId, (previous) => [
        ...previous,
        { id: `${Date.now()}-assistant-error`, role: "assistant", text: `Chat failed: ${message}` },
      ]);
    } finally {
      setChatLoading(false);
    }
  };

  const onStop = async () => {
    setBusy(true);
    setError("");
    try {
      const response = await stopAgent();
      setRuntimeStatus(response.status);
    } catch (stopError) {
      setError(stopError instanceof Error ? stopError.message : "Failed to stop agent");
    } finally {
      setBusy(false);
    }
  };

  return (
    <motion.div
      className="console-shell"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.4, ease: "easeOut" }}
    >
      <aside className="panel panel-left">
        <div className="panel-header">
          <h2>Sessions</h2>
          <button type="button" className="new-session-btn" onClick={onNewSession}>
            <span aria-hidden="true">+</span>
            New Session
          </button>
        </div>

        <div className="session-list" aria-label="Past sessions">
          {sessionHistory.length === 0 ? (
            <p className="sidebar-empty">No sessions yet</p>
          ) : (
            sessionHistory.map((session) => {
              const active = session.sessionId === activeSessionId;
              const stateClass = statusToUi(session.status);
              return (
                <button
                  key={session.sessionId}
                  type="button"
                  className={`session-card ${active ? "active" : ""}`}
                  onClick={() => setActiveSessionId(session.sessionId)}
                >
                  <p className="session-id-text">{truncate(session.sessionId, 14)}</p>
                  <p className="session-goal">{truncate(session.goal || "Untitled goal", 40)}</p>
                  <div className="session-meta">
                    <span className={`status-badge ${stateClass}`}>{session.status}</span>
                    <span>{formatTimestamp(session.updatedAt)}</span>
                  </div>
                </button>
              );
            })
          )}
        </div>
      </aside>

      <main className="panel panel-center">
        <div className="message-feed" ref={messageFeedRef}>
          {!activeSessionId && sessionHistory.length === 0 ? (
            <div className="empty-state">
              <div className="aurora-backdrop" aria-hidden="true">
                <span className="beam beam-a" />
                <span className="beam beam-b" />
                <span className="beam beam-c" />
              </div>
              <h1>Autonomous Agent Console</h1>
              <p>Start a session to run a goal and continue the thread just like Claude-style chat.</p>
            </div>
          ) : (
            <>
              {actionEvents.map((action) => {
                const expanded = Boolean(expandedActions[action.id]);
                return (
                  <div key={action.id} className="message-row assistant-row">
                    <div className="agent-text-block">
                      <button
                        type="button"
                        className="action-pill"
                        onClick={() =>
                          setExpandedActions((previous) => ({
                            ...previous,
                            [action.id]: !previous[action.id],
                          }))
                        }
                      >
                        <span aria-hidden="true">⚡</span>
                        Action: {action.summary}
                      </button>
                      <AnimatePresence initial={false}>
                        {expanded ? (
                          <motion.div
                            className="action-dropdown"
                            initial={{ opacity: 0, height: 0 }}
                            animate={{ opacity: 1, height: "auto" }}
                            exit={{ opacity: 0, height: 0 }}
                            transition={{ duration: 0.2, ease: "easeOut" }}
                          >
                            <p>
                              <strong>Raw action detail</strong>
                            </p>
                            <pre>{action.detail}</pre>
                            <p>
                              <strong>Tool call</strong>
                            </p>
                            <pre>{action.toolCall}</pre>
                            <p>
                              <strong>Result</strong>
                            </p>
                            <pre>{action.result}</pre>
                            <p className="action-time">{formatTimestamp(action.createdAt)}</p>
                          </motion.div>
                        ) : null}
                      </AnimatePresence>
                    </div>
                  </div>
                );
              })}

              {activeMessages.map((message) => (
                <div
                  key={message.id}
                  className={`message-row ${message.role === "user" ? "user-row" : "assistant-row"}`}
                >
                  {message.role === "user" ? (
                    <div className="user-bubble">{message.text}</div>
                  ) : (
                    <div className="agent-text-block markdown-block">
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm]}
                        components={{
                          code(props) {
                            const { className, children } = props as {
                              className?: string;
                              children?: ReactNode;
                            };
                            const text = String(children).replace(/\n$/, "");
                            const inline = !className;
                            if (inline) {
                              return <code className="inline-code">{text}</code>;
                            }

                            const language = className?.replace("language-", "") || "text";
                            return (
                              <div className="terminal-block">
                                <div className="terminal-header">
                                  <span>{language}</span>
                                  <button
                                    type="button"
                                    onClick={() => {
                                      void navigator.clipboard.writeText(text);
                                    }}
                                  >
                                    Copy
                                  </button>
                                </div>
                                <pre>
                                  <code>{text}</code>
                                  <span className="terminal-cursor" aria-hidden="true" />
                                </pre>
                              </div>
                            );
                          },
                        }}
                      >
                        {message.text}
                      </ReactMarkdown>
                    </div>
                  )}
                </div>
              ))}

              {outputs.map((line, index) => (
                <div key={`${index}-${line.slice(0, 22)}`} className="message-row assistant-row">
                  <div className="agent-text-block markdown-block">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{line}</ReactMarkdown>
                  </div>
                </div>
              ))}

              {(chatLoading || busy || uiState === "running") && <ThinkingDots />}
            </>
          )}
        </div>

        <form className="chat-input-bar" onSubmit={onSubmitInput}>
          <div className="input-wrap">
            <input
              value={chatInput}
              onChange={(event) => setChatInput(event.target.value)}
              placeholder={
                activeSessionId
                  ? "Message the agent about this session"
                  : "Describe the goal to start a new session"
              }
            />
            <button type="submit" disabled={busy || chatLoading}>
              Send
            </button>
          </div>
          <p className="session-footnote">
            Session: {activeSessionId ? truncate(activeSessionId, 18) : "none"} · Iteration: {iteration} · State: {runtimeStatus}
          </p>
          {error ? <p className="error-line">{error}</p> : null}
        </form>
      </main>

      <aside className="panel panel-right">
        <section className="status-card">
          <h3>Session Status</h3>
          <p className="status-line">
            <span className={`status-dot ${uiState}`} />
            <span className="status-label">State</span>
            <strong>{runtimeStatus}</strong>
          </p>
          <p className="status-line">
            <span className="status-label">Iteration</span>
            <strong>{iteration}</strong>
          </p>
          <p className="status-line session-inline-id">
            <span className="status-label">Session ID</span>
            <strong>{activeSessionId || "none"}</strong>
          </p>
          {uiState === "running" ? (
            <button type="button" className="stop-btn" onClick={onStop} disabled={busy}>
              Stop
            </button>
          ) : null}
        </section>

        <section className="logs-section">
          <h3>Agent Runtime Logs</h3>
          <div className="log-list" ref={runtimeLogsRef}>
            {logs.length === 0 ? (
              <p className="sidebar-empty">No runtime logs</p>
            ) : (
              logs.map((entry, index) => (
                <div key={`${entry.created_at}-${index}`} className="log-item">
                  <div className="log-head">
                    <span className={`level-badge ${logLevelClass(entry.level)}`}>{entry.level.toUpperCase()}</span>
                    <time>{formatTimestamp(entry.created_at)}</time>
                  </div>
                  <p className="log-text">{entry.message}</p>
                </div>
              ))
            )}
          </div>
        </section>

        <section className="logs-section">
          <button
            type="button"
            className="logs-toggle"
            onClick={() => setSystemLogsExpanded((previous) => !previous)}
          >
            <span>System & API Logs</span>
            <span className={`chevron ${systemLogsExpanded ? "open" : ""}`}>⌄</span>
          </button>
          <AnimatePresence initial={false}>
            {systemLogsExpanded ? (
              <motion.div
                className="log-list"
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                transition={{ duration: 0.2, ease: "easeOut" }}
              >
                {systemLogs.length === 0 ? (
                  <p className="sidebar-empty">No system logs</p>
                ) : (
                  systemLogs.map((entry, index) => (
                    <div key={`${entry.created_at}-${entry.source}-${index}`} className="log-item">
                      <div className="log-head">
                        <span className={`level-badge ${logLevelClass(entry.level)}`}>{entry.level.toUpperCase()}</span>
                        <time>{formatTimestamp(entry.created_at)}</time>
                      </div>
                      <p className="log-text">[{entry.source}] {entry.message}</p>
                    </div>
                  ))
                )}
              </motion.div>
            ) : null}
          </AnimatePresence>
        </section>

        <section className="session-mini-list">
          <h3>Recent Sessions</h3>
          {sessionHistory.slice(0, 4).map((session) => (
            <button
              type="button"
              key={`mini-${session.sessionId}`}
              className={`mini-session ${session.sessionId === activeSessionId ? "active" : ""}`}
              onClick={() => setActiveSessionId(session.sessionId)}
            >
              <span>{truncate(session.goal || "Untitled", 26)}</span>
              <strong>{truncate(session.sessionId, 10)}</strong>
            </button>
          ))}
          {sessionHistory.length === 0 ? <p className="sidebar-empty">No sessions tracked</p> : null}
        </section>
      </aside>
    </motion.div>
  );
}
