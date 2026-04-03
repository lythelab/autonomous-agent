from __future__ import annotations

from pathlib import Path
from typing import Any

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
