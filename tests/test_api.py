from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("fastapi")

from autonomous_agent import api


class FakeMemory:
    def get_full_episodes(self) -> list[dict[str, Any]]:
        return [
            {
                "key": "episode_1",
                "value": {
                    "step": "search",
                    "status": "running",
                    "result": {
                        "tool_calls": [
                            {"tool": "web_search", "input": "ai releases"},
                        ]
                    },
                },
                "entry_type": "full",
                "created_at": 1.0,
            },
            {
                "key": "episode_2",
                "value": {
                    "step": "rank",
                    "status": "completed",
                    "result": {
                        "tool_calls": [
                            {"tool": "run_code", "input": "print('rank')"},
                        ]
                    },
                },
                "entry_type": "full",
                "created_at": 2.0,
            },
        ]

    def get_summary(self) -> str:
        return "summary text"

    def get_context_pack(self, query: str | None = None, top_k: int = 5) -> dict[str, Any]:
        return {
            "summary": "summary text",
            "recent_episodes": [
                {
                    "key": "episode_2",
                    "value": {
                        "result": {
                            "output": "[report]\nTop finding: AI agents are being deployed in enterprise workflows.",
                        }
                    },
                }
            ],
            "matches": [
                {
                    "key": "episode_1",
                    "value": {
                        "result": {
                            "output": "[report]\nTop finding: Retrieval-augmented generation adoption is increasing.",
                        }
                    },
                }
            ],
        }


class FakeMemoryWithoutSummary(FakeMemory):
    def get_summary(self) -> str | None:
        return None


class FakeAgent:
    def __init__(self) -> None:
        self.memory = FakeMemory()


def test_logs_endpoint_returns_plain_text_lines(monkeypatch) -> None:
    monkeypatch.setattr(api, "_agent", FakeAgent())

    payload = api.get_logs(limit=1)

    assert "INFO [autonomous_agent.agent]" in payload
    assert "Summary: summary text" in payload
    assert "Step=rank status=completed" in payload
    assert "Tool called: run_code" in payload


def test_logs_endpoint_uses_fallback_summary_when_missing(monkeypatch) -> None:
    agent = FakeAgent()
    agent.memory = FakeMemoryWithoutSummary()
    monkeypatch.setattr(api, "_agent", agent)

    payload = api.get_logs(limit=2)

    assert "2 stored episode(s); recent steps: rank, search; latest status: completed" in payload


def test_env_endpoint_returns_backend_url(monkeypatch) -> None:
    monkeypatch.setenv("BACKEND_API_URL", "http://localhost:8000")

    payload = api.get_env()

    assert payload.backend_api_url == "http://localhost:8000"


def test_chat_endpoint_returns_answer_from_memory(monkeypatch) -> None:
    monkeypatch.setattr(api, "_agent", FakeAgent())

    payload = api.chat(api.ChatRequest(question="What trends were found?", top_k=5))

    assert payload["status"] == "ok"
    assert "Question: What trends were found?" in payload["answer"]
    assert len(payload["sources"]) >= 1


def test_chat_endpoint_handles_empty_context(monkeypatch) -> None:
    class EmptyMemory(FakeMemory):
        def get_context_pack(self, query: str | None = None, top_k: int = 5) -> dict[str, Any]:
            return {"summary": None, "recent_episodes": [], "matches": []}

    agent = FakeAgent()
    agent.memory = EmptyMemory()
    monkeypatch.setattr(api, "_agent", agent)

    payload = api.chat(api.ChatRequest(question="Any findings?", top_k=5))

    assert payload["status"] == "ok"
    assert "could not find relevant prior findings" in payload["answer"].lower()