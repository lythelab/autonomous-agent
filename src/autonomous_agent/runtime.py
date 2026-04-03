from __future__ import annotations

from pathlib import Path

from .agent_loop import AgentLoop
from .config import get_settings
from .memory_manager import MemoryManager
from .reflection_engine import ReflectionEngine
from .task_planner import TaskPlanner
from .tool_executor import ToolExecutor


def build_default_agent(
    db_path: str | Path | None = None,
    max_full_episodes: int | None = None,
    max_iterations: int | None = None,
    cycle_sleep_seconds: float | None = None,
) -> AgentLoop:
    """Build production-oriented wiring for E2B-backed autonomous operation."""
    settings = get_settings()
    resolved_db_path = db_path or settings.agent_db_path
    resolved_max_full = max_full_episodes or settings.max_full_episodes
    resolved_max_iterations = max_iterations or settings.max_iterations
    resolved_cycle_sleep = (
        cycle_sleep_seconds
        if cycle_sleep_seconds is not None
        else settings.cycle_sleep_seconds
    )

    memory = MemoryManager(db_path=resolved_db_path, max_full_episodes=resolved_max_full)
    planner = TaskPlanner()
    reflection_engine = ReflectionEngine()
    tool_executor = ToolExecutor()

    return AgentLoop(
        memory=memory,
        planner=planner,
        reflection_engine=reflection_engine,
        tool_executor=tool_executor,
        max_iterations=resolved_max_iterations,
        cycle_sleep_seconds=resolved_cycle_sleep,
    )


def start_autonomous_goal(
    goal: str,
    db_path: str | Path | None = None,
    runtime_seconds: float | None = None,
) -> dict:
    agent = build_default_agent(db_path=db_path)
    state = agent.load_state()

    if state.get("goal") != goal or state.get("status") in {"idle", "completed"}:
        agent.set_goal_autonomous(goal)

    return agent.run_forever(max_runtime_seconds=runtime_seconds)
