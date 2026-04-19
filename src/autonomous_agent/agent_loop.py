from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from .memory_manager import MemoryManager
from .reflection_engine import ReflectionEngine
from .state_tracker import StateTracker
from .task_planner import TaskPlanner
from .tool_executor import ToolExecutor


logger = logging.getLogger(__name__)


class AgentLoop:
    """Autonomous adaptive orchestration loop with persistent memory."""

    def __init__(
        self,
        memory: MemoryManager,
        state_key: str = "goal_state",
        executor: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
        tool_executor: ToolExecutor | None = None,
        planner: TaskPlanner | None = None,
        reflection_engine: ReflectionEngine | None = None,
        max_iterations: int = 1_000,
        cycle_sleep_seconds: float = 0.0,
        failure_backoff_seconds: float = 1.0,
        max_backoff_seconds: float = 30.0,
        stale_goal_failure_threshold: int = 6,
        snapshot_interval_cycles: int = 50,
    ) -> None:
        self.memory = memory
        self.state_tracker = StateTracker(memory=memory, state_key=state_key)
        self.executor = executor
        self.tool_executor = tool_executor
        self.planner = planner or TaskPlanner()
        self.reflection_engine = reflection_engine or ReflectionEngine()
        self.max_iterations = max_iterations
        self.cycle_sleep_seconds = cycle_sleep_seconds
        self.failure_backoff_seconds = max(0.0, failure_backoff_seconds)
        self.max_backoff_seconds = max(0.0, max_backoff_seconds)
        self.stale_goal_failure_threshold = max(1, stale_goal_failure_threshold)
        self.snapshot_interval_cycles = max(1, snapshot_interval_cycles)

    def load_state(self) -> dict[str, Any]:
        return self.state_tracker.load()

    def save_state(self, state: dict[str, Any]) -> None:
        self.state_tracker.save(state)

    def set_goal(self, goal: str, steps: list[str]) -> dict[str, Any]:
        return self.state_tracker.initialize_goal(goal=goal, steps=steps)

    def set_goal_autonomous(self, goal: str) -> dict[str, Any]:
        context = self.memory.get_context_pack(query=goal, top_k=5)
        steps = self.planner.create_plan(goal, context)
        return self.set_goal(goal, steps)

    def get_next_step(self) -> str | None:
        state = self.load_state()
        completed = set(state.get("completed_steps", []))
        for step in state.get("remaining_steps", []):
            if step not in completed:
                return step
        return None

    def execute_step(self, step: str) -> dict[str, Any]:
        state = self.load_state()
        result = self._execute(step, state)
        output_text = str(result.get("output", "") or "").strip()

        if result.get("status") == "ok":
            completed_steps = list(state.get("completed_steps", []))
            if step not in completed_steps:
                completed_steps.append(step)
            state["completed_steps"] = completed_steps
            state["remaining_steps"] = [
                item for item in state.get("remaining_steps", []) if item != step
            ]
            state["failure_count"] = 0
            state["consecutive_failures"] = 0
            if output_text:
                state["last_output"] = output_text
            state["last_error"] = None
            state["last_progress_at"] = time.time()
        else:
            state["failure_count"] = int(state.get("failure_count", 0)) + 1
            state["consecutive_failures"] = int(state.get("consecutive_failures", 0)) + 1
            state["last_error"] = str(result.get("error", "") or "").strip() or None
            if output_text:
                state["last_output"] = output_text

        state["iterations"] = int(state.get("iterations", 0)) + 1
        state["last_result"] = result

        reflection = self.reflection_engine.reflect(
            goal=state.get("goal") or "",
            step=step,
            result=result,
            state=state,
        )
        state.setdefault("strategy_notes", []).append(reflection.get("strategy_update"))

        if not state.get("remaining_steps"):
            state["status"] = "completed"
        elif result.get("status") != "ok":
            state["status"] = "running"
            revised = self.planner.revise_plan(
                goal=state.get("goal") or "",
                state=state,
                reflection=reflection,
            )
            state["remaining_steps"] = [
                candidate
                for candidate in revised
                if candidate not in state.get("completed_steps", [])
            ]
            self._maybe_refresh_stale_plan(state)
        else:
            state["status"] = "running"

        self.save_state(state)
        self.memory.write(
            f"episode_{int(time.time() * 1000)}",
            {
                "step": step,
                "result": result,
                "goal": state.get("goal"),
                "status": state["status"],
                "reflection": reflection,
            },
        )
        return result

    def run_cycle(self) -> dict[str, Any]:
        state = self.load_state()
        logger.info(
            "Starting cycle goal=%r status=%s remaining=%d completed=%d",
            state.get("goal"),
            state.get("status"),
            len(state.get("remaining_steps", [])),
            len(state.get("completed_steps", [])),
        )
        if state.get("goal") and not state.get("remaining_steps") and state.get("status") != "completed":
            context = self.memory.get_context_pack(query=state.get("goal"), top_k=5)
            replanned = self.planner.create_plan(state.get("goal"), context)
            state["remaining_steps"] = [
                step for step in replanned if step not in state.get("completed_steps", [])
            ]
            if state["remaining_steps"]:
                state["status"] = "running"
                self.save_state(state)

        next_step = self.get_next_step()
        if next_step is None:
            state = self.load_state()
            state["status"] = "completed"
            self.save_state(state)
            logger.info("Cycle completed: no remaining steps")
            self._post_cycle_maintenance()
            return {"status": "completed", "step": None, "result": None}

        logger.info("Executing step=%r", next_step)
        try:
            result = self.execute_step(next_step)
        except Exception as exc:  # noqa: BLE001 - loop should survive unexpected step failures
            logger.exception("Unhandled exception while executing step=%r", next_step)
            state = self.load_state()
            state["failure_count"] = int(state.get("failure_count", 0)) + 1
            state["consecutive_failures"] = int(state.get("consecutive_failures", 0)) + 1
            state["last_error"] = str(exc)
            state["iterations"] = int(state.get("iterations", 0)) + 1
            state["status"] = "running"
            state.setdefault("strategy_notes", []).append("Recovered from unexpected execution exception.")
            self._maybe_refresh_stale_plan(state)
            self.save_state(state)
            self._post_cycle_maintenance()
            return {
                "status": "failed",
                "step": next_step,
                "result": {"status": "failed", "error_type": "tool_error", "error": str(exc)},
                "state": self.load_state(),
            }
        logger.info(
            "Finished step=%r result_status=%s error=%r",
            next_step,
            result.get("status"),
            result.get("error"),
        )
        self._post_cycle_maintenance()
        return {
            "status": result.get("status", "unknown"),
            "step": next_step,
            "result": result,
            "state": self.load_state(),
        }

    def run(self, max_cycles: int | None = None) -> dict[str, Any]:
        cycles = 0
        limit = self.max_iterations if max_cycles is None else min(max_cycles, self.max_iterations)

        while cycles < limit:
            cycle_result = self.run_cycle()
            cycles += 1
            self._maybe_checkpoint(cycle_index=cycles, reason="run")
            if cycle_result["status"] == "completed":
                break
            self._sleep_for_current_state()

        return self.load_state()

    def run_forever(
        self,
        max_runtime_seconds: float | None = None,
        stop_when_completed: bool = False,
    ) -> dict[str, Any]:
        start = time.time()
        iterations = 0
        timeout_reached = False

        logger.info(
            "Run started max_runtime_seconds=%r stop_when_completed=%s",
            max_runtime_seconds,
            stop_when_completed,
        )

        while iterations < self.max_iterations:
            cycle_result = self.run_cycle()
            iterations += 1
            self._maybe_checkpoint(cycle_index=iterations, reason="run_forever")

            if stop_when_completed and cycle_result["status"] == "completed":
                logger.info("Run stopped because goal completed")
                break

            if max_runtime_seconds is not None and (time.time() - start) >= max_runtime_seconds:
                timeout_reached = True
                logger.info(
                    "Run stopped due to runtime limit elapsed=%.2fs limit=%.2fs",
                    time.time() - start,
                    max_runtime_seconds,
                )
                break

            self._sleep_for_current_state()

        final_state = self.load_state()
        if timeout_reached and final_state.get("status") != "completed":
            final_state["status"] = "timeout"
            self.save_state(final_state)

        logger.info(
            "Run ended status=%s iterations=%d remaining=%d",
            final_state.get("status"),
            int(final_state.get("iterations", 0)),
            len(final_state.get("remaining_steps", [])),
        )
        return self.load_state()

    def _default_executor(self, step: str, state: dict[str, Any]) -> dict[str, Any]:
        return {"status": "ok", "output": f"Completed step: {step}", "goal": state.get("goal")}

    def _execute(self, step: str, state: dict[str, Any]) -> dict[str, Any]:
        if self.executor is not None:
            return self.executor(step, state)

        if self.tool_executor is not None:
            return self.tool_executor.execute_task(step, state=state)

        return self._default_executor(step, state)

    def _post_cycle_maintenance(self) -> None:
        if self.tool_executor is not None:
            try:
                self.tool_executor.keep_alive()
            except Exception:
                # Keep-alive failure is non-fatal; execution path handles retries.
                pass

    def _sleep_for_current_state(self) -> None:
        state = self.load_state()
        consecutive_failures = int(state.get("consecutive_failures", 0))
        if consecutive_failures <= 0:
            sleep_seconds = self.cycle_sleep_seconds
        else:
            growth = 2 ** max(0, consecutive_failures - 1)
            adaptive = min(self.max_backoff_seconds, self.failure_backoff_seconds * growth)
            sleep_seconds = self.cycle_sleep_seconds + adaptive

        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    def _maybe_refresh_stale_plan(self, state: dict[str, Any]) -> None:
        failures = int(state.get("consecutive_failures", 0))
        if failures < self.stale_goal_failure_threshold:
            return

        goal = state.get("goal") or ""
        if not goal:
            return

        current_iteration = int(state.get("iterations", 0))
        last_refresh_iteration = int(state.get("last_plan_refresh_iteration", -1))
        if last_refresh_iteration == current_iteration:
            return

        context = self.memory.get_context_pack(query=goal, top_k=5)
        replanned = self.planner.create_plan(goal, context)
        refreshed = [
            step
            for step in replanned
            if step not in state.get("completed_steps", [])
        ]
        if not refreshed:
            refreshed = [f"search: {goal}"]

        state["remaining_steps"] = refreshed
        state["last_plan_refresh_iteration"] = current_iteration
        state.setdefault("strategy_notes", []).append(
            "Refreshed stale plan after repeated failures."
        )

    def _maybe_checkpoint(self, cycle_index: int, reason: str) -> None:
        if cycle_index % self.snapshot_interval_cycles != 0:
            return

        state = self.load_state()
        snapshot_key = f"checkpoint_{int(time.time() * 1000)}"
        self.memory.write(
            snapshot_key,
            {
                "entry_type": "checkpoint",
                "reason": reason,
                "cycle_index": cycle_index,
                "state": state,
            },
        )
