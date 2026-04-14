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
    e2b_require_sandbox: bool
    agent_db_path: str
    max_full_episodes: int
    max_iterations: int
    cycle_sleep_seconds: float


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
    return Settings(
        groq_api_key=os.getenv("GROQ_API_KEY"),
        groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        e2b_api_key=os.getenv("E2B_API_KEY"),
        e2b_template=os.getenv("E2B_TEMPLATE"),
        e2b_require_sandbox=require_sandbox,
        agent_db_path=os.getenv("AGENT_DB_PATH", "data/agent_state.db"),
        max_full_episodes=int(os.getenv("AGENT_MAX_FULL_EPISODES", "25")),
        max_iterations=int(os.getenv("AGENT_MAX_ITERATIONS", "100000")),
        cycle_sleep_seconds=float(os.getenv("AGENT_CYCLE_SLEEP_SECONDS", "5")),
    )


def clear_settings_cache() -> None:
    get_settings.cache_clear()
