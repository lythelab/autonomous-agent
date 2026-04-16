from __future__ import annotations

import io
import json
import logging
import time
from types import SimpleNamespace
from typing import Any

from .config import get_settings
from .e2b_handler import E2BHandler, E2BHandlerConfig


logger = logging.getLogger(__name__)


class LocalFallbackSandbox:
    """Minimal local execution fallback when E2B is unavailable."""

    def run_code(self, code: str) -> Any:
        stdout = io.StringIO()
        safe_builtins = {
            "print": lambda *args, **kwargs: print(*args, file=stdout, **kwargs),
            "len": len,
            "range": range,
            "min": min,
            "max": max,
            "sum": sum,
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "list": list,
            "dict": dict,
            "set": set,
            "tuple": tuple,
            "enumerate": enumerate,
            "__import__": __import__,
        }
        try:
            exec(code, {"__builtins__": safe_builtins}, {})  # noqa: S102 - controlled fallback path
            return SimpleNamespace(logs=stdout.getvalue().rstrip(), error=None)
        except Exception as exc:  # noqa: BLE001 - surfaced as tool error payload
            return SimpleNamespace(logs=stdout.getvalue().rstrip(), error=str(exc))


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
        self._allow_runtime_fallback = sandbox is None
        self.fallback_active = False
        self.sandbox_provider = "provided" if sandbox is not None else "auto"
        self.last_sandbox_error: str | None = None
        self.sandbox = sandbox or self._create_sandbox()
        logger.info(
            "ToolExecutor initialized provider=%s fallback_active=%s sandbox_type=%s",
            self.sandbox_provider,
            self.fallback_active,
            type(self.sandbox).__name__,
        )

    def run_code(self, code: str) -> dict[str, Any]:
        for attempt in range(self.max_retries):
            try:
                logger.debug(
                    "Running code attempt=%d/%d fallback_active=%s",
                    attempt + 1,
                    self.max_retries,
                    self.fallback_active,
                )
                result = self.sandbox.run_code(code)
                result_error = getattr(result, "error", None)
                if result_error:
                    return {
                        "status": "failed",
                        "error_type": "tool_error",
                        "error": str(result_error),
                        "output": self._extract_logs(result),
                    }
                return {
                    "status": "ok",
                    "output": self._extract_logs(result),
                    "error": None,
                }
            except Exception as exc:  # noqa: BLE001 - classification relies on runtime exception type
                logger.warning(
                    "Sandbox execution failed attempt=%d/%d error=%r",
                    attempt + 1,
                    self.max_retries,
                    exc,
                )
                if self._should_recreate_sandbox(exc):
                    recreated = self._recreate_sandbox(reason=exc)
                    if recreated:
                        continue
                if self._allow_runtime_fallback and not self.fallback_active:
                    self._activate_local_fallback(reason=exc)
                    continue
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
        if lower in {"update_goal_state", "update goal state"}:
            return {
                "status": "ok",
                "output": "Goal state updated.",
                "error": None,
            }
        if lower.startswith("search:"):
            return self.web_search(normalized.split(":", 1)[1].strip())
        if lower.startswith("fetch:"):
            return self.web_fetch(normalized.split(":", 1)[1].strip())
        if lower.startswith("code:"):
            return self.run_code(normalized.split(":", 1)[1].strip())
        if lower.startswith("summarize") or lower.startswith("summary"):
            return self._summarize_progress(task=normalized, state=state)
        if self._looks_like_research_task(normalized):
            query = self._build_research_query(normalized, state)
            return self.web_search(query)

        # Fallback keeps arbitrary natural-language steps executable.
        safe_payload = json.dumps(normalized)
        return self.run_code(f"print('TASK:', {safe_payload})")

    def _summarize_progress(self, task: str, state: dict[str, Any] | None) -> dict[str, Any]:
        if state is None:
            return self.web_search(task)

        goal = state.get("goal") or ""
        completed = state.get("completed_steps", [])
        last_output = (state.get("last_result") or {}).get("output") or ""
        
        summary_lines = [
            f"Goal: {goal}"
        ]
        
        if completed:
            summary_lines.append("Completed steps:")
            for step in completed:
                summary_lines.append(f"  - {step}")
        
        if last_output:
            summary_lines.append("Latest findings:")
            truncated = last_output[:500] if len(last_output) > 500 else last_output
            summary_lines.append(truncated)
        
        summary_lines.append("Summary: Focus notable release updates and report actionable changes.")
        
        output = "\n".join(summary_lines)
        safe_payload = json.dumps(output)
        return self.run_code(f"print({safe_payload})")

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

    def _build_research_query(self, task: str, state: dict[str, Any] | None) -> str:
        # Planner steps can be machine-like labels (e.g., check_ai_releases).
        # Convert them into a search-friendly query and fall back to goal text.
        normalized_task = task.replace("_", " ").replace("-", " ").strip()
        goal = (state or {}).get("goal") if state else None

        generic_labels = {
            "check ai releases",
            "monitor ai releases",
            "identify notable changes",
            "summarize notable changes",
            "update goal state",
        }

        if not normalized_task or normalized_task.lower() in generic_labels:
            if goal:
                return f"{goal} latest releases notable changes"
            return "latest ai model releases notable changes"

        if goal and len(normalized_task.split()) <= 3:
            return f"{goal} {normalized_task}"

        return normalized_task

    def web_search(self, query: str) -> dict[str, Any]:
        escaped_query = json.dumps(query)
        script = (
            "try:\n"
            "    from duckduckgo_search import DDGS\n"
            "except ModuleNotFoundError:\n"
            "    import subprocess\n"
            "    import sys\n"
            "    try:\n"
            "        subprocess.run([sys.executable, '-m', 'pip', 'install', 'duckduckgo_search', '-q'], check=True)\n"
            "        from duckduckgo_search import DDGS\n"
            "    except Exception:\n"
            "        DDGS = None\n"
            f"query = {escaped_query}\n"
            "results = []\n"
            "if DDGS is not None:\n"
            "    try:\n"
            "        results = list(DDGS().text(query, max_results=5))\n"
            "    except Exception:\n"
            "        results = []\n"
            "if not results:\n"
            "    print('No results found')\n"
            "for item in results:\n"
            "    print(f\"{item.get('title', '')} - {item.get('href', '')}\")\n"
        )
        result = self.run_code(script)
        if result.get("status") == "ok":
            return result
        return {
            "status": "failed",
            "error_type": result.get("error_type", "tool_error"),
            "error": result.get("error", "search failed"),
            "output": result.get("output"),
        }

    def web_fetch(self, url: str) -> dict[str, Any]:
        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=10) as response:
                content = response.read(2000).decode("utf-8", errors="ignore")
                return {
                    "status": "ok",
                    "output": content,
                    "error": None,
                }
        except Exception as exc:
            return {
                "status": "failed",
                "error_type": "tool_error",
                "error": str(exc),
            }

    def keep_alive(self) -> None:
        try:
            self.sandbox.run_code("print('ping')")
        except Exception as exc:  # noqa: BLE001 - keep alive failure should not crash the run
            if self._allow_runtime_fallback:
                if self._should_recreate_sandbox(exc):
                    recreated = self._recreate_sandbox(reason=exc)
                    if recreated:
                        return
                logger.warning("Sandbox keep_alive failed; switching to fallback error=%r", exc)
                self._activate_local_fallback(reason=exc)
            else:
                logger.warning("Sandbox keep_alive failed error=%r", exc)

    def classify_error(self, error: Exception) -> str:
        text = str(error).lower()
        if "rate_limit" in text or "429" in text:
            return "llm_error"
        if "sandbox" in text and "not found" in text:
            return "tool_error"
        if isinstance(error, (TimeoutError, ConnectionError)):
            return "tool_error"
        return "goal_ambiguity"

    def _create_sandbox(self) -> Any:
        settings = get_settings()
        return self._create_sandbox_with_settings(settings)

    def _create_sandbox_with_settings(self, settings: Any) -> Any:
        handler = self._build_e2b_handler(settings)

        try:
            sandbox = handler.create_sandbox()
            self.fallback_active = False
            self.sandbox_provider = "e2b"
            self.last_sandbox_error = None
            logger.info("E2B sandbox created successfully")
            return sandbox
        except Exception as exc:  # noqa: BLE001 - remote bootstrap can fail for many reasons
            if settings.e2b_require_sandbox:
                raise RuntimeError(f"E2B sandbox required but unavailable: {exc}") from exc
            logger.exception("Failed to create E2B sandbox; enabling fallback")
            return self._activate_local_fallback(reason=exc)

    def _build_e2b_handler(self, settings: Any) -> E2BHandler:
        handler = E2BHandler(
            E2BHandlerConfig(
                api_key=settings.e2b_api_key,
                template=settings.e2b_template,
                timeout_seconds=getattr(settings, "e2b_timeout_seconds", None),
                metadata={"service": "autonomous-agent"},
                require_sandbox=settings.e2b_require_sandbox,
            )
        )
        return handler

    def _should_recreate_sandbox(self, error: Exception) -> bool:
        if not self._allow_runtime_fallback:
            return False

        text = str(error).lower()
        stale_markers = (
            "sandbox was not found",
            "sandbox not found",
            '"sandboxid"',
        )
        if any(marker in text for marker in stale_markers) and "not found" in text:
            return True

        return False

    def _recreate_sandbox(self, reason: Exception) -> bool:
        logger.warning("Attempting sandbox recreation after runtime error=%r", reason)
        settings = get_settings()

        try:
            self.sandbox = self._create_sandbox_with_settings(settings)
            return not self.fallback_active
        except Exception as exc:  # noqa: BLE001 - preserve failure details for API status
            logger.exception("Sandbox recreation failed error=%r", exc)
            if settings.e2b_require_sandbox:
                raise
            self._activate_local_fallback(reason=exc)
            return False

    def _activate_local_fallback(self, reason: Exception) -> Any:
        self.last_sandbox_error = f"{type(reason).__name__}: {reason}"
        if not self.fallback_active:
            logger.warning(
                "Local sandbox fallback activated reason=%s details=%s",
                type(reason).__name__,
                str(reason),
            )
        self.fallback_active = True
        self.sandbox_provider = "local_fallback"
        self.sandbox = LocalFallbackSandbox()
        return self.sandbox

    def _extract_logs(self, result: Any) -> str:
        logs = getattr(result, "logs", "")
        if isinstance(logs, list):
            return "\n".join(str(item) for item in logs)
        return str(logs)
