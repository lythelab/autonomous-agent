from __future__ import annotations

from typing import Any


class ReflectionEngine:
    """Evaluate outcomes and produce adaptation hints for subsequent cycles."""

    def reflect(
        self,
        goal: str,
        step: str,
        result: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        status = result.get("status")
        error_text = str(result.get("error", "")).lower()
        lowered_goal = (goal or "").lower()
        lowered_step = (step or "").lower()

        if status == "ok":
            return {
                "outcome": "success",
                "insight": f"Step succeeded: {step}",
                "strategy_update": "Continue current strategy.",
                "next_step_suggestion": None,
                "confidence": 0.9,
            }

        failures = int(state.get("failure_count", 0))

        if lowered_step.startswith("fetch:"):
            next_step = f"search: {goal} alternative sources"
        elif "rate_limit" in error_text or result.get("error_type") == "llm_error":
            next_step = f"search: {goal} reliable sources"
        elif result.get("error_type") == "tool_error":
            if failures >= 3:
                next_step = f"search: {goal} broader context and alternative approaches"
            else:
                next_step = f"search: {goal} fallback sources"
        else:
            next_step = (
                "summarize: Synthesize current evidence for goal: "
                f"{goal}. Avoid placeholders and identify missing evidence clearly."
            )

        return {
            "outcome": "failure",
            "insight": f"Step failed: {step}",
            "strategy_update": "Adjust approach using fallback path.",
            "next_step_suggestion": next_step,
            "confidence": max(0.2, 0.8 - (failures * 0.1)),
        }
