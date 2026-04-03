from __future__ import annotations

import json
import re
from typing import Any

from .config import get_settings

try:
    from groq import Groq
except ImportError:  # pragma: no cover - optional dependency for local test runs
    Groq = None


class TaskPlanner:
    """Create and revise execution plans from high-level goals."""

    def __init__(
        self,
        groq_client: Any | None = None,
        model: str | None = None,
    ) -> None:
        settings = get_settings()
        self.groq_client = groq_client
        self.model = model or settings.groq_model

    def create_plan(self, goal: str, memory_context: dict[str, Any] | None = None) -> list[str]:
        context = memory_context or {}
        if self.groq_client is None and not get_settings().groq_api_key:
            return self._heuristic_plan(goal)

        try:
            response = self._client().chat.completions.create(
                model=self.model,
                temperature=0,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a task planner for a long-running autonomous agent. "
                            "Return a concise JSON array of executable task strings."
                        ),
                    },
                    {
                        "role": "user",
                        "content": self._build_plan_prompt(goal, context),
                    },
                ],
            )
            content = response.choices[0].message.content.strip()
            return self._parse_plan(content) or self._heuristic_plan(goal)
        except Exception:
            return self._heuristic_plan(goal)

    def revise_plan(
        self,
        goal: str,
        state: dict[str, Any],
        reflection: dict[str, Any],
    ) -> list[str]:
        remaining = list(state.get("remaining_steps", []))
        completed = list(state.get("completed_steps", []))
        suggestion = reflection.get("next_step_suggestion")

        if suggestion and suggestion not in completed and suggestion not in remaining:
            return [suggestion] + remaining

        if remaining:
            return remaining

        return self.create_plan(goal, {"state": state, "reflection": reflection})

    def _client(self) -> Any:
        if self.groq_client is not None:
            return self.groq_client
        if Groq is None:
            raise RuntimeError("Groq SDK is not installed.")
        api_key = get_settings().groq_api_key
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is required for Groq planner mode.")
        return Groq(api_key=api_key)

    def _build_plan_prompt(self, goal: str, context: dict[str, Any]) -> str:
        return (
            "Goal:\n"
            f"{goal}\n\n"
            "Memory context (JSON):\n"
            f"{json.dumps(context, sort_keys=True)}\n\n"
            "Return only JSON array of short executable tasks."
        )

    def _parse_plan(self, content: str) -> list[str]:
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text.replace("json", "", 1).strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return []

        if not isinstance(parsed, list):
            return []

        steps: list[str] = []
        for item in parsed:
            if isinstance(item, str) and item.strip():
                steps.append(item.strip())
        return steps

    def _heuristic_plan(self, goal: str) -> list[str]:
        chunks = [part.strip(" .") for part in re.split(r"[.;]|\band\b", goal, flags=re.IGNORECASE)]
        chunks = [part for part in chunks if part]

        if chunks:
            return [f"code: print({json.dumps(part)})" for part in chunks[:8]]

        return [
            "code: print('Clarify goal requirements')",
            "code: print('Execute primary objective')",
            "code: print('Summarize outcome and next actions')",
        ]
