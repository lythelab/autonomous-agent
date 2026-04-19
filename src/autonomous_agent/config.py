from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional in local environments until dependencies are synced
    load_dotenv = None


@dataclass(frozen=True)
class Settings:
    groq_api_key: str | None
    groq_model: str
    e2b_api_key: str | None
    e2b_template: str | None
    e2b_timeout_seconds: int | None
    e2b_require_sandbox: bool
    agent_db_path: str
    max_full_episodes: int
    max_iterations: int
    cycle_sleep_seconds: float
    failure_backoff_seconds: float
    max_backoff_seconds: float
    stale_goal_failure_threshold: int
    snapshot_interval_cycles: int


def load_environment(dotenv_path: str | Path | None = None) -> None:
    if load_dotenv is None:
        return
    path = Path(dotenv_path) if dotenv_path is not None else Path(".env")
    load_dotenv(dotenv_path=path, override=False)


@lru_cache(maxsize=1)
def get_settings(dotenv_path: str | Path | None = None) -> Settings:
    load_environment(dotenv_path)
    require_sandbox = os.getenv("E2B_REQUIRE_SANDBOX", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    timeout_raw = (os.getenv("E2B_TIMEOUT_SECONDS") or "").strip()
    timeout_seconds = int(timeout_raw) if timeout_raw else None
    return Settings(
        groq_api_key=os.getenv("GROQ_API_KEY"),
        groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        e2b_api_key=os.getenv("E2B_API_KEY"),
        e2b_template=os.getenv("E2B_TEMPLATE"),
        e2b_timeout_seconds=timeout_seconds,
        e2b_require_sandbox=require_sandbox,
        agent_db_path=os.getenv("AGENT_DB_PATH", "data/agent_state.db"),
        max_full_episodes=int(os.getenv("AGENT_MAX_FULL_EPISODES", "25")),
        max_iterations=int(os.getenv("AGENT_MAX_ITERATIONS", "100000")),
        cycle_sleep_seconds=float(os.getenv("AGENT_CYCLE_SLEEP_SECONDS", "5")),
        failure_backoff_seconds=float(os.getenv("AGENT_FAILURE_BACKOFF_SECONDS", "1.0")),
        max_backoff_seconds=float(os.getenv("AGENT_MAX_BACKOFF_SECONDS", "30.0")),
        stale_goal_failure_threshold=int(os.getenv("AGENT_STALE_FAILURE_THRESHOLD", "6")),
        snapshot_interval_cycles=int(os.getenv("AGENT_SNAPSHOT_INTERVAL_CYCLES", "50")),
    )


def clear_settings_cache() -> None:
    get_settings.cache_clear()
