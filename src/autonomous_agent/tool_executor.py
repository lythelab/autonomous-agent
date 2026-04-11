from __future__ import annotations

import json
import time
from typing import Any

from .config import get_settings

try:
    from e2b_code_interpreter import Sandbox
except ImportError:  # pragma: no cover - optional dependency for local test runs
    Sandbox = None


class ToolExecutor:
    """Execute code and web tasks in a reusable sandbox with retries."""

    def __init__(
        self,
        sandbox: Any | None = None,
        max_retries: int = 3,
        retry_delay_seconds: float = 0.0,
    ) -> None:
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds
        self.sandbox = sandbox or self._create_sandbox()

    def run_code(self, code: str) -> dict[str, Any]:
        for attempt in range(self.max_retries):
            try:
                result = self.sandbox.run_code(code)
                return {
                    "status": "ok",
                    "output": self._extract_logs(result),
                    "error": getattr(result, "error", None),
                }
            except Exception as exc:  # noqa: BLE001 - classification relies on runtime exception type
                if attempt == self.max_retries - 1:
                    return {
                        "status": "failed",
                        "error_type": self.classify_error(exc),
                        "error": str(exc),
                    }
                if self.retry_delay_seconds > 0:
                    time.sleep(self.retry_delay_seconds)
        return {"status": "failed", "error_type": "tool_error", "error": "unknown"}

    def execute_task(self, task: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized = task.strip()
        if not normalized:
            return {"status": "failed", "error_type": "goal_ambiguity", "error": "Empty task"}

        lower = normalized.lower()
        if lower.startswith("search:"):
            return self.web_search(normalized.split(":", 1)[1].strip())
        if lower.startswith("fetch:"):
            return self.web_fetch(normalized.split(":", 1)[1].strip())
        if lower.startswith("code:"):
            return self.run_code(normalized.split(":", 1)[1].strip())
        if lower.startswith("summarize") or lower.startswith("summary"):
            return self._summarize_progress(task=normalized, state=state)
        if self._looks_like_research_task(normalized):
            return self.web_search(normalized)

        # Fallback keeps arbitrary natural-language steps executable.
        safe_payload = json.dumps(normalized)
        return self.run_code(f"print('TASK:', {safe_payload})")

    def _summarize_progress(self, task: str, state: dict[str, Any] | None) -> dict[str, Any]:
        if state is None:
            return self.web_search(task)

        safe_goal = json.dumps(state.get("goal") or "")
        safe_completed = json.dumps(state.get("completed_steps", []))
        safe_last_output = json.dumps((state.get("last_result") or {}).get("output") or "")
        code = (
            f"goal = {safe_goal}\n"
            f"completed = {safe_completed}\n"
            f"last_output = {safe_last_output}\n"
            "print(f'Goal: {goal}')\n"
            "if completed:\n"
            "    print('Completed steps:')\n"
            "    for step in completed:\n"
            "        print(f'- {step}')\n"
            "if last_output:\n"
            "    print('Latest findings:')\n"
            "    print(last_output)\n"
            "print('Summary: Focus notable release updates, compare to prior behavior, and report actionable changes.')\n"
        )
        return self.run_code(code)

    def _looks_like_research_task(self, task: str) -> bool:
        lowered = task.lower()
        keywords = (
            "check",
            "monitor",
            "research",
            "identify",
            "find",
            "release",
            "news",
            "latest",
            "changes",
            "update",
        )
        return any(token in lowered for token in keywords)

    def web_search(self, query: str) -> dict[str, Any]:
        safe_query = json.dumps(query)
        code = (
            "from duckduckgo_search import DDGS\n"
            f"results = list(DDGS().text({safe_query}, max_results=5))\n"
            "for item in results:\n"
            "    print(item.get('title', ''), '-', item.get('href', ''))\n"
        )
        return self.run_code(code)

    def web_fetch(self, url: str) -> dict[str, Any]:
        safe_url = json.dumps(url)
        code = (
            "import urllib.request\n"
            f"with urllib.request.urlopen({safe_url}, timeout=10) as response:\n"
            "    print(response.read(2000).decode('utf-8', errors='ignore'))\n"
        )
        return self.run_code(code)

    def keep_alive(self) -> None:
        self.sandbox.run_code("print('ping')")

    def classify_error(self, error: Exception) -> str:
        text = str(error).lower()
        if "rate_limit" in text or "429" in text:
            return "llm_error"
        if isinstance(error, (TimeoutError, ConnectionError)):
            return "tool_error"
        return "goal_ambiguity"

    def _create_sandbox(self) -> Any:
        if Sandbox is None:
            raise RuntimeError(
                "e2b-code-interpreter is not installed. Install it or provide a sandbox instance."
            )
        if not get_settings().e2b_api_key:
            raise RuntimeError("E2B_API_KEY is not configured. Set it in your environment or .env file.")
        return Sandbox.create()

    def _extract_logs(self, result: Any) -> str:
        logs = getattr(result, "logs", "")
        if isinstance(logs, list):
            return "\n".join(str(item) for item in logs)
        return str(logs)
