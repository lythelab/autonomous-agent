from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from autonomous_agent import ToolExecutor


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
