from __future__ import annotations

import os
import time
from threading import Lock
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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


def _build_logs_payload(limit: int = 20) -> dict[str, Any]:
    full_episodes = list(reversed(_agent.memory.get_full_episodes()))
    safe_limit = max(1, min(limit, 100))
    tool_executor = getattr(_agent, "tool_executor", None)
    return {
        "summary": _agent.memory.get_summary(),
        "recent_episodes": full_episodes[:safe_limit],
        "count": len(full_episodes),
        "executor": {
            "enabled": tool_executor is not None,
            "sandbox_provider": getattr(tool_executor, "sandbox_provider", None),
            "fallback_active": getattr(tool_executor, "fallback_active", None),
            "last_sandbox_error": getattr(tool_executor, "last_sandbox_error", None),
        },
    }


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


@app.get("/logs")
def get_logs(limit: int = 20) -> dict[str, Any]:
    with _lock:
        return _build_logs_payload(limit=limit)


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
