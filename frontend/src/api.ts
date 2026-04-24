export type StartResponse = {
  session_id: string;
  status: string;
};

export type AgentSession = {
  session_id: string;
  goal: string;
  status: string;
  iteration: number;
  last_output: string;
  started_at: string;
  updated_at: string;
};

export type StatusResponse = {
  session: AgentSession | null;
  outputs: string[];
};

export type OutputResponse = {
  session_id: string;
  status: string;
  outputs: string[];
};

export type LogEntry = {
  id?: number;
  session_id: string;
  iteration: number;
  level: string;
  message: string;
  created_at: string;
};

export type LogsResponse = {
  session_id: string;
  logs: LogEntry[];
};

export type SystemLogEntry = {
  id?: number;
  level: string;
  source: string;
  message: string;
  request_id: string;
  created_at: string;
};

export type SystemLogsResponse = {
  logs: SystemLogEntry[];
};

export type ChatResponse = {
  session_id: string;
  answer: string;
};

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });

  if (!response.ok) {
    const errorBody = await response.text();
    throw new Error(errorBody || `Request failed: ${response.status}`);
  }

  return (await response.json()) as T;
}

export async function startAgent(goal: string, sessionId?: string): Promise<StartResponse> {
  return request<StartResponse>("/agent/start", {
    method: "POST",
    body: JSON.stringify({ goal, session_id: sessionId || null }),
  });
}

export async function stopAgent(): Promise<{ status: string }> {
  return request<{ status: string }>("/agent/stop", { method: "POST" });
}

export async function getStatus(sessionId: string): Promise<StatusResponse> {
  const params = new URLSearchParams({ session_id: sessionId });
  return request<StatusResponse>(`/agent/status?${params.toString()}`);
}

export async function getOutput(sessionId: string, limit = 200): Promise<OutputResponse> {
  const params = new URLSearchParams({
    session_id: sessionId,
    limit: String(limit),
  });
  return request<OutputResponse>(`/agent/output?${params.toString()}`);
}

export async function getLogs(sessionId: string, limit = 200): Promise<LogsResponse> {
  const params = new URLSearchParams({
    session_id: sessionId,
    limit: String(limit),
  });
  return request<LogsResponse>(`/agent/logs?${params.toString()}`);
}

export async function getSystemLogs(limit = 300): Promise<SystemLogsResponse> {
  const params = new URLSearchParams({
    limit: String(limit),
  });
  return request<SystemLogsResponse>(`/system/logs?${params.toString()}`);
}

export async function askSessionQuestion(sessionId: string, question: string): Promise<ChatResponse> {
  return request<ChatResponse>("/agent/chat", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, question }),
  });
}
