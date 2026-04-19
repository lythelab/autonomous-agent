from __future__ import annotations

import json
import re
from urllib.parse import urlparse
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
                            "Return ONLY a JSON array of 3-6 executable task strings. "
                            "Each task must be directly runnable by this agent and should use one of these prefixes when relevant: "
                            "search:, fetch:, code:, summarize:. "
                            "Do not return generic placeholders. "
                            "The final task must be a summarize task that synthesizes concrete evidence collected so far. "
                            "Do not request fixed templates or rigid output formats."
                        ),
                    },
                    {
                        "role": "user",
                        "content": self._build_plan_prompt(goal, context),
                    },
                ],
            )
            content = response.choices[0].message.content.strip()
            parsed = self._parse_plan(content)
            normalized = self._normalize_steps(parsed, goal=goal)
            return normalized or self._heuristic_plan(goal)
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
            "Return only a JSON array of executable tasks. "
            "Prefer concrete web searches over vague steps. "
            "Always include a final summarize task that synthesizes findings and clearly states missing evidence."
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

    def _normalize_steps(self, steps: list[str], goal: str) -> list[str]:
        seen: set[str] = set()
        normalized: list[str] = []

        for step in steps:
            candidate = step.strip()
            if not candidate:
                continue

            lowered = candidate.lower()
            if lowered.startswith("fetch:"):
                safe_step = self._normalize_fetch_step(candidate, goal)
                if safe_step:
                    candidate = safe_step

            key = candidate.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(candidate)

        summarize_steps = [s for s in normalized if s.lower().startswith("summarize:")]
        non_summarize_steps = [s for s in normalized if not s.lower().startswith("summarize:")]

        if not non_summarize_steps:
            non_summarize_steps = [f"search: {goal}".strip()]

        final_summarize = summarize_steps[-1] if summarize_steps else self._final_summarize_step(goal)

        return [*non_summarize_steps[:5], final_summarize]

    def _normalize_fetch_step(self, step: str, goal: str) -> str:
        raw = step.split(":", 1)[1].strip() if ":" in step else ""
        if not raw:
            return f"search: {goal}"

        parsed = urlparse(raw)
        host = parsed.netloc.lower()
        blocked_hosts = {
            "www.amazon.com",
            "amazon.com",
            "www.cnet.com",
            "cnet.com",
            "www.pcmag.com",
            "pcmag.com",
            "www.rtings.com",
            "rtings.com",
        }

        if host in blocked_hosts:
            return f"search: {goal} site:{host}"

        return step

    def _heuristic_plan(self, goal: str) -> list[str]:
        normalized_goal = " ".join(goal.split()).strip()
        if not normalized_goal:
            return [
                "search: latest AI and technology updates",
                "summarize: Synthesize the strongest findings collected so far and identify what evidence is still missing.",
            ]

        lowered = normalized_goal.lower()
        research_markers = (
            "search",
            "research",
            "latest",
            "trend",
            "news",
            "find",
            "analyze",
            "report",
            "summary",
            "summarize",
            "startup",
            "yc",
            "conversational",
            "ai",
        )
        is_research_goal = any(marker in lowered for marker in research_markers)

        if is_research_goal:
            return [
                f"search: {normalized_goal}",
                f"search: {normalized_goal} site:ycombinator.com OR site:techcrunch.com OR site:venturebeat.com",
                self._final_summarize_step(normalized_goal),
            ]

        chunks = [part.strip(" .") for part in re.split(r"[.;]|\band\b", normalized_goal, flags=re.IGNORECASE)]
        chunks = [part for part in chunks if part]

        if chunks:
            steps: list[str] = [f"search: {chunks[0]}"]
            if len(chunks) > 1:
                steps.extend(f"search: {part}" for part in chunks[1:3])
            steps.append(self._final_summarize_step(normalized_goal))
            return steps

        return [
            f"search: {normalized_goal}",
            self._final_summarize_step(normalized_goal),
        ]

    def _final_summarize_step(self, goal: str) -> str:
        return (
            "summarize: Synthesize the best answer for goal: "
            f"{goal}. Use concrete evidence from completed steps only, avoid placeholders, and call out missing information explicitly."
        )
