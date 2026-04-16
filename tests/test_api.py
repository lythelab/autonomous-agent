from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("fastapi")

from autonomous_agent import api


class FakeMemory:
    def get_full_episodes(self) -> list[dict[str, Any]]:
        return [
            {"key": "episode_1", "value": {"step": "search"}, "entry_type": "full"},
            {"key": "episode_2", "value": {"step": "rank"}, "entry_type": "full"},
        ]

    def get_summary(self) -> str:
        return "summary text"


class FakeMemoryWithoutSummary(FakeMemory):
    def get_summary(self) -> str | None:
        return None


class FakeAgent:
    def __init__(self) -> None:
        self.memory = FakeMemory()


def test_logs_endpoint_returns_recent_episodes(monkeypatch) -> None:
    monkeypatch.setattr(api, "_agent", FakeAgent())

    payload = api.get_logs(limit=1)

    assert payload["summary"] == "summary text"
    assert payload["count"] == 2
    assert len(payload["recent_episodes"]) == 1
    assert payload["recent_episodes"][0]["key"] == "episode_2"


def test_logs_endpoint_uses_fallback_summary_when_missing(monkeypatch) -> None:
    agent = FakeAgent()
    agent.memory = FakeMemoryWithoutSummary()
    monkeypatch.setattr(api, "_agent", agent)

    payload = api.get_logs(limit=2)

    assert payload["summary"] == "2 stored episode(s); recent steps: rank, search"


def test_env_endpoint_returns_backend_url(monkeypatch) -> None:
    monkeypatch.setenv("BACKEND_API_URL", "http://localhost:8000")

    payload = api.get_env()

    assert payload.backend_api_url == "http://localhost:8000"