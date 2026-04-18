from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from autonomous_agent import ToolExecutor
from autonomous_agent import tool_executor as tool_executor_module


class FakeSandbox:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def run_code(self, code: str) -> Any:
        self.calls.append(code)
        return SimpleNamespace(logs="hello from sandbox", error=None)


class FlakySandbox:
    def __init__(self) -> None:
        self.calls = 0

    def run_code(self, code: str) -> Any:
        self.calls += 1
        if self.calls == 1:
            raise Exception("sandbox error")
        return SimpleNamespace(logs="ok", error=None)


class TimeoutSandbox:
    def __init__(self) -> None:
        self.calls = 0

    def run_code(self, code: str) -> Any:
        self.calls += 1
        raise TimeoutError("timed out")


class MissingSandboxErrorSandbox:
    def __init__(self) -> None:
        self.calls = 0

    def run_code(self, code: str) -> Any:
        self.calls += 1
        raise Exception(
            'TimeoutException: {"sandboxId":"abc","message":"The sandbox was not found","code":502}'
        )


class WrappedLogsSandbox:
    def run_code(self, code: str) -> Any:
        return SimpleNamespace(
            logs='Logs(stdout: ["Goal: search AI trends and summarize a report\\nCompleted steps:\\n  - search_ai_trends\\nLatest findings:\\nLogs(stdout: [\'TASK: search_ai_trends\\\\n\'], stderr: [])\\nSummary: Focus notable release updates and report actionable changes.\\n"], stderr: [])',
            error=None,
        )


def test_run_code_returns_output() -> None:
    executor = ToolExecutor(sandbox=FakeSandbox())

    result = executor.run_code("print('hello from sandbox')")

    assert result["status"] == "ok"
    assert "hello from sandbox" in result["output"]


def test_web_search_runs_inside_sandbox() -> None:
    sandbox = FakeSandbox()
    executor = ToolExecutor(sandbox=sandbox)

    result = executor.web_search("Groq Llama models")

    assert result["status"] == "ok"
    assert any("DDGS" in call for call in sandbox.calls)


def test_run_code_retries_on_failure() -> None:
    sandbox = FlakySandbox()
    executor = ToolExecutor(sandbox=sandbox, max_retries=3)

    result = executor.run_code("print('test')")

    assert result["status"] == "ok"
    assert sandbox.calls == 2


def test_tool_fails_after_max_retries() -> None:
    sandbox = TimeoutSandbox()
    executor = ToolExecutor(sandbox=sandbox, max_retries=3)

    result = executor.run_code("print('test')")

    assert result["status"] == "failed"
    assert result["error_type"] == "tool_error"
    assert sandbox.calls == 3


def test_executor_recreates_stale_sandbox_before_fallback(monkeypatch) -> None:
    stale = MissingSandboxErrorSandbox()
    healthy = FakeSandbox()
    sandboxes = [stale, healthy]
    calls = {"create": 0}

    def fake_create_sandbox_with_settings(self: ToolExecutor, _settings: Any) -> Any:
        index = calls["create"]
        calls["create"] += 1
        return sandboxes[index]

    monkeypatch.setattr(ToolExecutor, "_create_sandbox_with_settings", fake_create_sandbox_with_settings)

    executor = ToolExecutor()
    result = executor.run_code("print('recovered')")

    assert result["status"] == "ok"
    assert calls["create"] == 2
    assert executor.fallback_active is False


def test_rate_limit_classified_as_llm_error() -> None:
    executor = ToolExecutor(sandbox=FakeSandbox())

    assert executor.classify_error(Exception("rate_limit exceeded")) == "llm_error"


def test_timeout_classified_as_tool_error() -> None:
    executor = ToolExecutor(sandbox=FakeSandbox())

    assert executor.classify_error(TimeoutError("timed out")) == "tool_error"


def test_keep_alive_prevents_timeout() -> None:
    sandbox = FakeSandbox()
    executor = ToolExecutor(sandbox=sandbox)

    executor.keep_alive()
    result = executor.run_code("print('still alive')")

    assert result["status"] == "ok"
    assert sandbox.calls[0] == "print('ping')"


def test_execute_task_routes_search_prefix() -> None:
    sandbox = FakeSandbox()
    executor = ToolExecutor(sandbox=sandbox)

    result = executor.execute_task("search: autonomous agents")

    assert result["status"] == "ok"
    assert any("DDGS" in call for call in sandbox.calls)


def test_execute_task_summarize_task_uses_state_context() -> None:
    sandbox = FakeSandbox()
    executor = ToolExecutor(sandbox=sandbox)

    result = executor.execute_task(
        "Summarize the latest run",
        state={
            "goal": "Monitor AI releases",
            "completed_steps": ["Check release notes"],
            "last_result": {"output": "Found release highlights"},
        },
    )

    assert result["status"] == "ok"
    assert any("Summary:" in call for call in sandbox.calls)


def test_execute_task_plain_research_text_uses_web_search() -> None:
    sandbox = FakeSandbox()
    executor = ToolExecutor(sandbox=sandbox)

    result = executor.execute_task("Check AI release notes")

    assert result["status"] == "ok"
    assert any("DDGS" in call for call in sandbox.calls)


def test_execute_task_underscore_step_uses_goal_query() -> None:
    sandbox = FakeSandbox()
    executor = ToolExecutor(sandbox=sandbox)

    result = executor.execute_task(
        "check_ai_releases",
        state={"goal": "Monitor AI releases and summarize notable changes"},
    )

    assert result["status"] == "ok"
    assert any("AI model release notes OpenAI Anthropic Google DeepMind Meta xAI" in call for call in sandbox.calls)


def test_execute_task_search_ai_trends_routes_to_web_search() -> None:
    sandbox = FakeSandbox()
    executor = ToolExecutor(sandbox=sandbox)

    result = executor.execute_task(
        "search_ai_trends",
        state={"goal": "search for latest AI trends and make a report"},
    )

    assert result["status"] == "ok"
    assert any("DDGS" in call for call in sandbox.calls)


def test_run_code_parses_wrapped_logs_output() -> None:
    executor = ToolExecutor(sandbox=WrappedLogsSandbox())

    result = executor.run_code("print('ignored')")

    assert result["status"] == "ok"
    assert "Logs(stdout:" not in result["output"]
    assert result["output"].startswith("[report]\nGoal: search AI trends")
    assert "TASK: search_ai_trends" in result["output"]


def test_executor_uses_fallback_when_e2b_create_fails(monkeypatch) -> None:
    settings = SimpleNamespace(
        e2b_api_key="test",
        e2b_template=None,
        e2b_require_sandbox=False,
    )

    class BrokenHandler:
        def __init__(self, _config: Any) -> None:
            pass

        def create_sandbox(self) -> Any:
            raise RuntimeError("e2b unavailable")

    monkeypatch.setattr(tool_executor_module, "get_settings", lambda: settings)
    monkeypatch.setattr(tool_executor_module, "E2BHandler", BrokenHandler)

    executor = ToolExecutor()

    assert executor.fallback_active is True
    assert executor.sandbox_provider == "local_fallback"


def test_executor_raises_when_e2b_required(monkeypatch) -> None:
    settings = SimpleNamespace(
        e2b_api_key="test",
        e2b_template=None,
        e2b_require_sandbox=True,
    )

    class BrokenHandler:
        def __init__(self, _config: Any) -> None:
            pass

        def create_sandbox(self) -> Any:
            raise RuntimeError("e2b unavailable")

    monkeypatch.setattr(tool_executor_module, "get_settings", lambda: settings)
    monkeypatch.setattr(tool_executor_module, "E2BHandler", BrokenHandler)

    try:
        ToolExecutor()
    except RuntimeError as exc:
        assert "required" in str(exc).lower()
    else:
        raise AssertionError("Expected RuntimeError when E2B sandbox is required")
