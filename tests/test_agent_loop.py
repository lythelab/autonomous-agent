from __future__ import annotations

from pathlib import Path
from typing import Any

import autonomous_agent.agent_loop as agent_loop_module
from autonomous_agent import AgentLoop, MemoryManager, ReflectionEngine, TaskPlanner, ToolExecutor


class StubPlanner(TaskPlanner):
    def __init__(self, steps: list[str]) -> None:
        self.steps = steps

    def create_plan(self, goal: str, memory_context: dict[str, Any] | None = None) -> list[str]:
        return list(self.steps)

    def revise_plan(self, goal: str, state: dict[str, Any], reflection: dict[str, Any]) -> list[str]:
        suggestion = reflection.get("next_step_suggestion")
        if suggestion:
            return [suggestion] + list(state.get("remaining_steps", []))
        return list(state.get("remaining_steps", []))


class StubReflectionEngine(ReflectionEngine):
    def reflect(
        self,
        goal: str,
        step: str,
        result: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        if result.get("status") == "ok":
            return {
                "outcome": "success",
                "strategy_update": "continue",
                "next_step_suggestion": None,
            }
        return {
            "outcome": "failure",
            "strategy_update": "fallback",
            "next_step_suggestion": "code: print('fallback step')",
        }


class KeepAliveSandbox:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def run_code(self, code: str) -> Any:
        self.calls.append(code)
        return {"logs": "ok", "error": None}


def test_agent_resumes_from_saved_state(tmp_path: Path) -> None:
    memory = MemoryManager(db_path=tmp_path / "resume.db")
    memory.write(
        "goal_state",
        {
            "goal": "Summarize AI news",
            "completed_steps": ["fetch_headlines"],
            "remaining_steps": ["analyze", "write_summary"],
            "status": "running",
            "iterations": 1,
            "last_result": None,
        },
    )

    agent = AgentLoop(memory=memory)
    state = agent.load_state()

    assert state["completed_steps"] == ["fetch_headlines"]


def test_state_saved_after_each_step(tmp_path: Path) -> None:
    memory = MemoryManager(db_path=tmp_path / "handoff.db")
    agent = AgentLoop(memory=memory)
    agent.set_goal("Do analysis", ["analyze"])

    agent.execute_step("analyze")
    saved = memory.read("goal_state")

    assert saved is not None
    assert "analyze" in saved["completed_steps"]


def test_agent_skips_completed_steps(tmp_path: Path) -> None:
    memory = MemoryManager(db_path=tmp_path / "skip.db")
    memory.write(
        "goal_state",
        {
            "goal": "Test skip",
            "completed_steps": ["step_A", "step_B"],
            "remaining_steps": ["step_C"],
            "status": "running",
            "iterations": 2,
            "last_result": None,
        },
    )

    agent = AgentLoop(memory=memory)

    assert agent.get_next_step() == "step_C"


def test_agent_initializes_fresh_state(tmp_path: Path) -> None:
    memory = MemoryManager(db_path=tmp_path / "fresh.db")
    agent = AgentLoop(memory=memory)

    state = agent.load_state()

    assert state["completed_steps"] == []
    assert state["remaining_steps"] == []
    assert state["status"] == "idle"


def test_agent_marks_completed_goal(tmp_path: Path) -> None:
    memory = MemoryManager(db_path=tmp_path / "done.db")
    agent = AgentLoop(memory=memory)
    agent.set_goal("Single step", ["step_1"])

    result = agent.run_cycle()

    assert result["status"] == "ok"
    final_state = agent.load_state()
    assert final_state["status"] == "completed"
    assert final_state["remaining_steps"] == []


def test_agent_generates_plan_from_goal(tmp_path: Path) -> None:
    memory = MemoryManager(db_path=tmp_path / "auto_plan.db")
    planner = StubPlanner(["code: print('one')", "code: print('two')"])
    agent = AgentLoop(memory=memory, planner=planner)

    state = agent.set_goal_autonomous("Do two steps")

    assert state["remaining_steps"] == ["code: print('one')", "code: print('two')"]
    assert state["status"] == "running"


def test_agent_adapts_plan_after_failure(tmp_path: Path) -> None:
    memory = MemoryManager(db_path=tmp_path / "adapt.db")
    calls = {"count": 0}

    def flaky_executor(step: str, state: dict[str, Any]) -> dict[str, Any]:
        calls["count"] += 1
        if calls["count"] == 1:
            return {"status": "failed", "error_type": "tool_error", "error": "temporary"}
        return {"status": "ok", "output": step}

    agent = AgentLoop(
        memory=memory,
        executor=flaky_executor,
        planner=StubPlanner(["code: print('main step')"]),
        reflection_engine=StubReflectionEngine(),
    )
    agent.set_goal("Adaptive run", ["code: print('main step')"])

    first = agent.run_cycle()
    second = agent.run_cycle()

    assert first["status"] == "failed"
    assert second["status"] == "ok"
    state = agent.load_state()
    assert "fallback" in state["strategy_notes"]


def test_agent_calls_tool_keep_alive_each_cycle(tmp_path: Path) -> None:
    memory = MemoryManager(db_path=tmp_path / "keep_alive.db")
    sandbox = KeepAliveSandbox()
    tool_executor = ToolExecutor(sandbox=sandbox)
    agent = AgentLoop(memory=memory, tool_executor=tool_executor)
    agent.set_goal("Use tool", ["code: print('hello')"])

    agent.run_cycle()

    assert "print('ping')" in sandbox.calls


def test_run_forever_marks_timeout_when_runtime_limit_hit(tmp_path: Path) -> None:
    memory = MemoryManager(db_path=tmp_path / "timeout.db")
    agent = AgentLoop(memory=memory)
    agent.set_goal("Two steps", ["step_1", "step_2"])

    state = agent.run_forever(max_runtime_seconds=0)

    assert state["status"] == "timeout"
    assert state["completed_steps"] == ["step_1"]
    assert state["remaining_steps"] == ["step_2"]


def test_agent_preserves_last_output_after_failure(tmp_path: Path) -> None:
    memory = MemoryManager(db_path=tmp_path / "last_output.db")
    responses = iter(
        [
            {"status": "ok", "output": "first useful output"},
            {"status": "failed", "error_type": "tool_error", "error": "fetch blocked"},
        ]
    )

    def sequenced_executor(step: str, state: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        return next(responses)

    agent = AgentLoop(
        memory=memory,
        executor=sequenced_executor,
        planner=StubPlanner(["search: first", "fetch: blocked"]),
        reflection_engine=StubReflectionEngine(),
    )
    agent.set_goal("Compare options", ["search: first", "fetch: blocked"])

    agent.run_cycle()
    agent.run_cycle()
    state = agent.load_state()

    assert state["last_output"] == "first useful output"
    assert state["last_error"] == "fetch blocked"


def test_run_uses_adaptive_backoff_after_failures(tmp_path: Path, monkeypatch) -> None:
    memory = MemoryManager(db_path=tmp_path / "backoff.db")

    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(agent_loop_module.time, "sleep", fake_sleep)

    def failing_executor(step: str, state: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        return {"status": "failed", "error_type": "tool_error", "error": "temporary"}

    agent = AgentLoop(
        memory=memory,
        executor=failing_executor,
        cycle_sleep_seconds=0.0,
        failure_backoff_seconds=0.1,
        max_backoff_seconds=0.4,
    )
    agent.set_goal("Backoff goal", ["step_1", "step_2", "step_3"])

    agent.run(max_cycles=3)

    # After repeated failures, sleep should increase and clamp to max_backoff_seconds.
    assert sleeps[:3] == [0.1, 0.2, 0.4]


def test_run_forever_writes_periodic_checkpoints(tmp_path: Path) -> None:
    memory = MemoryManager(db_path=tmp_path / "checkpoint.db")
    agent = AgentLoop(memory=memory, snapshot_interval_cycles=1)
    agent.set_goal("Checkpoint goal", ["step_1", "step_2"])

    agent.run(max_cycles=2)

    records = memory.search("checkpoint", top_k=10)
    assert any(str(record.get("key", "")).startswith("checkpoint_") for record in records)


def test_agent_refreshes_stale_plan_after_repeated_failures(tmp_path: Path) -> None:
    memory = MemoryManager(db_path=tmp_path / "stale_refresh.db")

    class RefreshPlanner(TaskPlanner):
        def create_plan(self, goal: str, memory_context: dict[str, Any] | None = None) -> list[str]:  # noqa: ARG002
            return ["search: refreshed approach", "summarize: refreshed"]

        def revise_plan(self, goal: str, state: dict[str, Any], reflection: dict[str, Any]) -> list[str]:  # noqa: ARG002
            return ["search: original failing path"]

    def failing_executor(step: str, state: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        return {"status": "failed", "error_type": "tool_error", "error": "still failing"}

    agent = AgentLoop(
        memory=memory,
        executor=failing_executor,
        planner=RefreshPlanner(),
        stale_goal_failure_threshold=2,
    )
    agent.set_goal("Refresh goal", ["search: original failing path"])

    agent.run_cycle()
    agent.run_cycle()

    state = agent.load_state()
    assert state["remaining_steps"][0] == "search: refreshed approach"
    assert any("Refreshed stale plan" in note for note in state.get("strategy_notes", []))
