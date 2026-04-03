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

        if status == "ok":
            return {
                "outcome": "success",
                "insight": f"Step succeeded: {step}",
                "strategy_update": "Continue current strategy.",
                "next_step_suggestion": None,
                "confidence": 0.9,
            }

        if "rate_limit" in error_text or result.get("error_type") == "llm_error":
            next_step = "code: print('Backoff and retry with lower frequency')"
        elif result.get("error_type") == "tool_error":
            next_step = "code: print('Use fallback tool path and retry')"
        else:
            next_step = "code: print('Clarify ambiguous objective then retry')"

        failures = int(state.get("failure_count", 0)) + 1
        return {
            "outcome": "failure",
            "insight": f"Step failed: {step}",
            "strategy_update": "Adjust approach using fallback path.",
            "next_step_suggestion": next_step,
            "confidence": max(0.2, 0.8 - (failures * 0.1)),
        }
