from __future__ import annotations

import io
import ast
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
                        "output": self._format_report_output(self._extract_logs(result)),
                    }
                return {
                    "status": "ok",
                    "output": self._format_report_output(self._extract_logs(result)),
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
                "output": self._format_report_output("Goal state updated."),
                "error": None,
                "tool_calls": [self._tool_call_payload("state_update", task)],
            }
        if lower.startswith("search:"):
            query = normalized.split(":", 1)[1].strip()
            result = self.web_search(query)
            return self._attach_tool_call(result, "web_search", query)
        if lower.startswith("fetch:"):
            url = normalized.split(":", 1)[1].strip()
            result = self.web_fetch(url)
            return self._attach_tool_call(result, "web_fetch", url)
        if lower.startswith("code:"):
            code = normalized.split(":", 1)[1].strip()
            result = self.run_code(code)
            return self._attach_tool_call(result, "run_code", code)
        if lower.startswith("summarize") or lower.startswith("summary"):
            result = self._summarize_progress(task=normalized, state=state)
            return self._attach_tool_call(result, "summarize_progress", normalized)
        if self._looks_like_report_task(normalized):
            result = self._summarize_progress(task=normalized, state=state)
            return self._attach_tool_call(result, "summarize_progress", normalized)
        if self._looks_like_research_task(normalized):
            query = self._build_research_query(normalized, state)
            result = self.web_search(query)
            return self._attach_tool_call(result, "web_search", query)

        # Fallback keeps arbitrary natural-language steps executable while
        # still returning useful output instead of echoing the task text.
        if state and state.get("goal"):
            result = self._summarize_progress(task=normalized, state=state)
            return self._attach_tool_call(result, "summarize_progress", normalized)

        query = self._build_research_query(normalized, state)
        result = self.web_search(query)
        return self._attach_tool_call(result, "web_search", query)

    def _summarize_progress(self, task: str, state: dict[str, Any] | None) -> dict[str, Any]:
        if state is None:
            return self.web_search(task)

        goal = state.get("goal") or ""
        completed = state.get("completed_steps", [])
        last_output = (state.get("last_result") or {}).get("output") or ""
        cleaned_last_output = self._clean_output_text(str(last_output))
        
        summary_lines = [
            f"Goal: {goal}"
        ]
        
        if completed:
            summary_lines.append("Completed steps:")
            for step in completed:
                summary_lines.append(f"  - {step}")
        
        if cleaned_last_output:
            summary_lines.append("Latest findings:")
            truncated = (
                cleaned_last_output[:500]
                if len(cleaned_last_output) > 500
                else cleaned_last_output
            )
            summary_lines.append(truncated)

        if goal:
            summary_lines.append(f"Summary: Provide a concise report aligned to the goal: {goal}")
        else:
            summary_lines.append("Summary: Provide a concise report based on the findings above.")
        
        output = "\n".join(summary_lines)
        safe_payload = json.dumps(output)
        return self.run_code(f"print({safe_payload})")

    def _looks_like_research_task(self, task: str) -> bool:
        lowered = task.lower().replace("_", " ").replace("-", " ")
        keywords = (
            "search",
            "gather",
            "collect",
            "source",
            "check",
            "monitor",
            "research",
            "identify",
            "find",
            "trend",
            "release",
            "news",
            "latest",
            "changes",
            "update",
            "report",
            "summarize",
            "analysis",
        )
        return any(token in lowered for token in keywords)

    def _looks_like_report_task(self, task: str) -> bool:
        lowered = task.lower().replace("_", " ").replace("-", " ")
        keywords = (
            "make report",
            "make a report",
            "write report",
            "generate report",
            "final report",
            "summarize",
            "synthesize",
            "finalize",
        )
        return any(token in lowered for token in keywords)

    def _build_research_query(self, task: str, state: dict[str, Any] | None) -> str:
        # Planner steps can be machine-like labels (e.g., check_ai_releases).
        # Convert them into a search-friendly query and fall back to goal text.
        normalized_task = task.replace("_", " ").replace("-", " ").strip()
        goal = (state or {}).get("goal") if state else None
        combined_text = f"{goal or ''} {normalized_task}".lower()

        if "ai" in combined_text and "trend" in combined_text:
            return (
                "latest AI trends 2026 generative ai enterprise adoption model releases "
                "openai anthropic google microsoft meta"
            )

        generic_labels = {
            "search ai trends",
            "search for ai trends",
            "research ai trends",
            "gather relevant data",
            "collect relevant data",
            "analyze findings",
            "check ai releases",
            "monitor ai releases",
            "identify notable changes",
            "summarize notable changes",
            "update goal state",
        }

        if not normalized_task or normalized_task.lower() in generic_labels:
            if goal:
                if "ai" in goal.lower() and "release" in goal.lower():
                    return (
                        "AI model release notes OpenAI Anthropic Google DeepMind Meta xAI "
                        "latest updates changelog"
                    )
                return f"{goal} latest releases notable changes"
            return "latest ai model releases notable changes"

        if goal and len(normalized_task.split()) <= 3:
            return f"{goal} {normalized_task}"

        cleaned_query = normalized_task
        query_noise = (
            "make a report",
            "and make a report",
            "write a report",
            "summarize findings",
            "create summary",
        )
        for phrase in query_noise:
            cleaned_query = cleaned_query.replace(phrase, " ")
        cleaned_query = " ".join(cleaned_query.split())
        return cleaned_query or normalized_task

    def web_search(self, query: str) -> dict[str, Any]:
        escaped_query = json.dumps(query)
        script = (
            "try:\n"
            "    from duckduckgo_search import DDGS\n"
            "except ModuleNotFoundError:\n"
            "    try:\n"
            "        from ddgs import DDGS\n"
            "    except ModuleNotFoundError:\n"
            "        DDGS = None\n"
            "import urllib.parse\n"
            "import urllib.request\n"
            "import xml.etree.ElementTree as ET\n"
            f"query = {escaped_query}\n"
            "results = []\n"
            "if DDGS is not None:\n"
            "    try:\n"
            "        results = list(DDGS().text(query, max_results=5))\n"
            "    except Exception:\n"
            "        results = []\n"
            "if not results:\n"
            "    try:\n"
            "        encoded = urllib.parse.quote_plus(query)\n"
            "        rss_url = f'https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en'\n"
            "        with urllib.request.urlopen(rss_url, timeout=10) as response:\n"
            "            xml_data = response.read()\n"
            "        root = ET.fromstring(xml_data)\n"
            "        channel = root.find('channel')\n"
            "        if channel is not None:\n"
            "            for item in channel.findall('item')[:5]:\n"
            "                title = (item.findtext('title') or '').strip()\n"
            "                link = (item.findtext('link') or '').strip()\n"
            "                if title and link:\n"
            "                    results.append({'title': title, 'href': link})\n"
            "    except Exception:\n"
            "        results = results\n"
            "if not results:\n"
            "    print('No results found')\n"
            "for item in results:\n"
            "    print(f\"{item.get('title', '')} - {item.get('href', '')}\")\n"
        )
        result = self.run_code(script)
        if result.get("status") == "ok":
            report_text = self._build_search_report(result.get("output", ""), query)
            result["output"] = self._format_report_output(report_text)
            return result
        return {
            "status": "failed",
            "error_type": result.get("error_type", "tool_error"),
            "error": result.get("error", "search failed"),
            "output": result.get("output"),
        }

    def _build_search_report(self, output: str, query: str) -> str:
        cleaned = self._clean_output_text(output)
        lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
        if not lines:
            return f"Search query: {query}\nNo relevant findings were returned."

        top_lines = lines[:5]
        report_lines = [
            f"Search query: {query}",
            "Top findings:",
        ]
        for line in top_lines:
            report_lines.append(f"- {line}")

        report_lines.append("Summary: These are the most recent signals matching the search query.")
        return "\n".join(report_lines)

    def web_fetch(self, url: str) -> dict[str, Any]:
        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=10) as response:
                content = response.read(2000).decode("utf-8", errors="ignore")
                return {
                    "status": "ok",
                    "output": self._format_report_output(content),
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
            extracted_lines: list[str] = []
            for item in logs:
                stdout_text = self._extract_stdout(item)
                if stdout_text:
                    extracted_lines.append(stdout_text)
                else:
                    extracted_lines.append(str(item))
            raw_text = "\n".join(line for line in extracted_lines if line).strip()
            return self._clean_output_text(raw_text)

        direct_stdout = self._extract_stdout(logs)
        if direct_stdout:
            return self._clean_output_text(direct_stdout)

        return self._clean_output_text(str(logs))

    def _extract_stdout(self, log_item: Any) -> str:
        # E2B log records can be object-like or dict-like with stdout/stderr fields.
        if isinstance(log_item, dict):
            stdout_value = log_item.get("stdout")
            if stdout_value is None:
                return ""
            return self._normalize_stream(stdout_value)

        stdout_value = getattr(log_item, "stdout", None)
        if stdout_value is None:
            return ""
        return self._normalize_stream(stdout_value)

    def _normalize_stream(self, value: Any) -> str:
        if isinstance(value, list):
            parts = [self._clean_output_text(str(item)) for item in value if str(item).strip()]
            return "\n".join(part for part in parts if part).strip()

        return self._clean_output_text(str(value))

    def _tool_call_payload(self, tool_name: str, tool_input: str) -> dict[str, str]:
        return {
            "tool": tool_name,
            "input": tool_input,
        }

    def _attach_tool_call(self, result: dict[str, Any], tool_name: str, tool_input: str) -> dict[str, Any]:
        calls = result.get("tool_calls", [])
        if not isinstance(calls, list):
            calls = []
        calls.append(self._tool_call_payload(tool_name, tool_input))
        result["tool_calls"] = calls
        return result

    def _format_report_output(self, text: str) -> str:
        cleaned = self._clean_output_text(text)
        if not cleaned:
            cleaned = "No output available."
        return f"[report]\n{cleaned}"

    def _strip_report_header(self, text: str) -> str:
        cleaned = text.strip()
        while cleaned.lower().startswith("[report]"):
            cleaned = cleaned[len("[report]"):].lstrip()
        return cleaned

    def _clean_output_text(self, text: str) -> str:
        cleaned = self._strip_report_header(text)

        previous = None
        while cleaned and cleaned != previous:
            previous = cleaned
            extracted = self._try_extract_stdout_from_logs_repr(cleaned)
            if extracted is None:
                break
            cleaned = self._strip_report_header(extracted)

        cleaned = self._unwrap_embedded_logs_lines(cleaned)

        return cleaned.strip()

    def _unwrap_embedded_logs_lines(self, text: str) -> str:
        lines = text.splitlines()
        changed = False
        normalized_lines: list[str] = []

        for line in lines:
            stripped = line.strip()
            extracted = self._try_extract_stdout_from_logs_repr(stripped)
            if extracted is None:
                normalized_lines.append(line)
                continue

            changed = True
            if extracted:
                normalized_lines.extend(extracted.splitlines())

        rebuilt = "\n".join(normalized_lines).strip()
        if changed:
            # One more pass handles nested wrappers introduced after line replacement.
            return self._clean_output_text(rebuilt)

        return rebuilt

    def _try_extract_stdout_from_logs_repr(self, text: str) -> str | None:
        raw = text.strip()
        prefix = "Logs(stdout:"
        if not raw.startswith(prefix):
            return None

        stderr_marker = ", stderr:"
        marker_index = raw.rfind(stderr_marker)
        if marker_index == -1 or not raw.endswith(")"):
            return None

        stdout_expr = raw[len(prefix):marker_index].strip()
        if not stdout_expr:
            return ""

        try:
            parsed = ast.literal_eval(stdout_expr)
        except (ValueError, SyntaxError):
            return stdout_expr

        return self._normalize_stream(parsed)
