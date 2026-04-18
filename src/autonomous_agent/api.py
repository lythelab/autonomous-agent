from __future__ import annotations

import os
import time
from datetime import datetime
from threading import Lock
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from .config import get_settings
from .runtime import build_default_agent

app = FastAPI(title="Autonomous Agent API", version="0.1.0")

allowed_origins = [
    origin.strip()
    for origin in os.getenv("FRONTEND_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_agent = build_default_agent(cycle_sleep_seconds=0.0)
_lock = Lock()


class GoalRequest(BaseModel):
    goal: str = Field(min_length=1, description="High-level objective for the agent")


class RunRequest(BaseModel):
    max_cycles: int = Field(default=1, ge=1, le=10_000)


class EnvResponse(BaseModel):
    backend_api_url: str = Field(default="", description="Backend API base URL configured via environment")
    e2b_enabled: bool = Field(default=False, description="Whether E2B API key is configured")
    e2b_template: str | None = Field(default=None, description="Configured E2B template")


def _summarize_recent_episodes(full_episodes: list[dict[str, Any]]) -> str | None:
    if not full_episodes:
        return None

    recent_episodes = full_episodes[:3]
    recent_steps = []
    latest_status = None

    for episode in recent_episodes:
        episode_value = episode.get("value") if isinstance(episode, dict) else None
        if not isinstance(episode_value, dict):
            continue

        step = episode_value.get("step")
        if isinstance(step, str) and step.strip():
            recent_steps.append(step.strip())

        if latest_status is None:
            latest_status = episode_value.get("status")

        if latest_status is None:
            result_value = episode_value.get("result")
            if isinstance(result_value, dict):
                latest_status = result_value.get("status")

    parts = [f"{len(full_episodes)} stored episode(s)"]
    if recent_steps:
        parts.append(f"recent steps: {', '.join(recent_steps)}")
    if isinstance(latest_status, str) and latest_status.strip():
        parts.append(f"latest status: {latest_status.strip()}")

    return "; ".join(parts)


def _format_log_line(level: str, message: str, timestamp: float | None = None) -> str:
    if timestamp is None:
        dt = datetime.now()
    else:
        dt = datetime.fromtimestamp(timestamp)
    stamp = dt.strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
    return f"{stamp} {level} [autonomous_agent.agent] {message}"


def _extract_tool_calls(episode_value: dict[str, Any]) -> list[dict[str, str]]:
    result_value = episode_value.get("result")
    if not isinstance(result_value, dict):
        return []

    calls = result_value.get("tool_calls", [])
    if not isinstance(calls, list):
        return []

    normalized_calls: list[dict[str, str]] = []
    for call in calls:
        if not isinstance(call, dict):
            continue
        tool_name = str(call.get("tool", "")).strip()
        tool_input = str(call.get("input", "")).strip()
        if not tool_name:
            continue
        normalized_calls.append({"tool": tool_name, "input": tool_input})
    return normalized_calls


def _build_logs_text(limit: int = 20) -> str:
    full_episodes = list(reversed(_agent.memory.get_full_episodes()))
    safe_limit = max(1, min(limit, 100))
    summary = _agent.memory.get_summary() or _summarize_recent_episodes(full_episodes)

    lines: list[str] = []
    lines.append(_format_log_line("INFO", f"Loaded {len(full_episodes)} episode(s)"))
    if summary:
        lines.append(_format_log_line("INFO", f"Summary: {summary}"))

    for episode in full_episodes[:safe_limit]:
        if not isinstance(episode, dict):
            continue

        episode_value = episode.get("value")
        if not isinstance(episode_value, dict):
            continue

        step = str(episode_value.get("step", "")).strip() or "unknown_step"
        status = str(episode_value.get("status", "")).strip() or "unknown"
        created_at = episode.get("created_at")
        level = "INFO" if status in {"running", "completed"} else "ERROR"
        lines.append(_format_log_line(level, f"Step={step} status={status}", timestamp=created_at))

        for tool_call in _extract_tool_calls(episode_value):
            tool_input = tool_call["input"]
            if len(tool_input) > 120:
                tool_input = f"{tool_input[:117]}..."
            lines.append(
                _format_log_line(
                    "INFO",
                    f"Tool called: {tool_call['tool']} input={tool_input}",
                    timestamp=created_at,
                )
            )

    return "\n".join(lines)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/env", response_model=EnvResponse)
def get_env() -> EnvResponse:
    settings = get_settings()
    return EnvResponse(
        backend_api_url=os.getenv("BACKEND_API_URL", ""),
        e2b_enabled=bool(settings.e2b_api_key),
        e2b_template=settings.e2b_template,
    )


@app.get("/state")
def get_state() -> dict[str, Any]:
    with _lock:
        return _agent.load_state()


@app.get("/logs", response_class=PlainTextResponse)
def get_logs(limit: int = 20) -> str:
    with _lock:
        return _build_logs_text(limit=limit)


@app.post("/goal")
def set_goal(payload: GoalRequest) -> dict[str, Any]:
    with _lock:
        state = _agent.set_goal_autonomous(payload.goal)
    return {"status": "ok", "state": state}


@app.post("/cycle")
def run_cycle() -> dict[str, Any]:
    with _lock:
        return _agent.run_cycle()


@app.post("/run")
def run(payload: RunRequest) -> dict[str, Any]:
    with _lock:
        state = _agent.run(max_cycles=payload.max_cycles)
    return {"status": "ok", "state": state}


@app.post("/reset")
def reset() -> dict[str, Any]:
    with _lock:
        state = {
            "goal": None,
            "completed_steps": [],
            "remaining_steps": [],
            "status": "idle",
            "iterations": 0,
            "failure_count": 0,
            "strategy_notes": [],
            "last_result": None,
            "updated_at": time.time(),
        }
        _agent.save_state(state)
    return {"status": "ok", "state": state}
