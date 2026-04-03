from __future__ import annotations

import time
from typing import Any

from .memory_manager import MemoryManager


class StateTracker:
    """Persistent state wrapper for goal lifecycle and progress updates."""

    def __init__(self, memory: MemoryManager, state_key: str = "goal_state") -> None:
        self.memory = memory
        self.state_key = state_key

    def load(self) -> dict[str, Any]:
        state = self.memory.read(self.state_key)
        if state is None:
            state = self._default_state()
            self.save(state)
        return state

    def save(self, state: dict[str, Any]) -> None:
        state["updated_at"] = time.time()
        self.memory.write(self.state_key, state)

    def initialize_goal(self, goal: str, steps: list[str]) -> dict[str, Any]:
        state = self.load()
        state.update(
            {
                "goal": goal,
                "completed_steps": [],
                "remaining_steps": list(steps),
                "status": "running" if steps else "completed",
                "iterations": 0,
                "failure_count": 0,
                "strategy_notes": [],
                "last_result": None,
            }
        )
        self.save(state)
        return state

    def _default_state(self) -> dict[str, Any]:
        return {
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
