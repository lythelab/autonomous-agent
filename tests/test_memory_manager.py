from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from autonomous_agent import MemoryManager


class FakeGroqClient:
    def __init__(self) -> None:
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create_completion))

    def _create_completion(self, *args, **kwargs):
        self.calls += 1
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Groq summary of old episodes."))]
        )


def test_memory_write_and_read(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    manager = MemoryManager(db_path=db_path)

    manager.write("episode_1", {"action": "search", "result": "ok"})
    result = manager.read("episode_1")

    assert result == {"action": "search", "result": "ok"}


def test_memory_persists_after_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "test_persist.db"

    manager = MemoryManager(db_path=db_path)
    manager.write("key", {"value": 42})
    manager.close()

    new_manager = MemoryManager(db_path=db_path)
    result = new_manager.read("key")

    assert result == {"value": 42}


def test_compression_reduces_episode_count(tmp_path: Path) -> None:
    db_path = tmp_path / "test_compress.db"
    fake_client = FakeGroqClient()
    manager = MemoryManager(db_path=db_path, max_full_episodes=5, groq_client=fake_client)

    for index in range(10):
        manager.write(f"episode_{index}", {"step": index, "data": "x" * 500})

    full_episodes = manager.get_full_episodes()

    assert len(full_episodes) <= 5
    assert manager.get_summary() == "Groq summary of old episodes."
    assert fake_client.calls >= 1


def test_memory_confidence_weighted_by_recency(tmp_path: Path) -> None:
    db_path = tmp_path / "test_confidence.db"
    manager = MemoryManager(db_path=db_path)

    manager.write("old_episode", {"data": "stale"}, timestamp=1_000_000.0)
    manager.write("new_episode", {"data": "fresh"}, timestamp=2_000_000.0)

    results = manager.search("data", top_k=2)

    assert results[0]["key"] == "new_episode"


def test_duplicate_key_overwrites_existing_value(tmp_path: Path) -> None:
    db_path = tmp_path / "test_duplicate.db"
    manager = MemoryManager(db_path=db_path)

    manager.write("duplicate", {"value": 1})
    manager.write("duplicate", {"value": 2})

    assert manager.read("duplicate") == {"value": 2}


def test_empty_database_returns_no_values(tmp_path: Path) -> None:
    db_path = tmp_path / "test_empty.db"
    manager = MemoryManager(db_path=db_path)

    assert manager.read("missing") is None
    assert manager.get_full_episodes() == []
    assert manager.get_summary() is None
