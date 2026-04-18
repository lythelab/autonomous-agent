from __future__ import annotations

from autonomous_agent.task_planner import TaskPlanner


def test_heuristic_plan_for_research_goal_uses_search_and_summarize() -> None:
    planner = TaskPlanner(groq_client=None)

    steps = planner.create_plan("search for latest conversational AI trends at YC startups")

    assert len(steps) >= 3
    assert all(isinstance(step, str) and step for step in steps)
    assert steps[0].startswith("search:")
    assert any(step.startswith("summarize:") for step in steps)


def test_heuristic_plan_for_empty_goal_still_returns_executable_steps() -> None:
    planner = TaskPlanner(groq_client=None)

    steps = planner.create_plan("   ")

    assert len(steps) >= 2
    assert steps[0].startswith("search:")
    assert steps[-1].startswith("summarize:")
