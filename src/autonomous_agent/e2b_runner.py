from dataclasses import dataclass

from e2b_code_interpreter import Sandbox


@dataclass
class ExecutionResult:
    stdout: str
    stderr: str
    success: bool


class E2BExecutor:
    def __init__(self, api_key: str, timeout_seconds: int = 3600, step_timeout_seconds: int = 120) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._step_timeout_seconds = step_timeout_seconds
        self._sandbox: Sandbox | None = None

    def _get_sandbox(self) -> Sandbox:
        if self._sandbox is None:
            self._sandbox = Sandbox(api_key=self._api_key, timeout=self._timeout_seconds)
        return self._sandbox

    def run_python(self, code: str) -> ExecutionResult:
        sandbox = self._get_sandbox()
        try:
            execution = sandbox.run_code(
                code,
                timeout=self._step_timeout_seconds,
                request_timeout=self._step_timeout_seconds + 15,
            )
        except Exception as exc:  # pylint: disable=broad-except
            return ExecutionResult(stdout="", stderr=str(exc), success=False)

        stdout = (execution.text or "").strip()
        stderr = ""

        if getattr(execution, "error", None):
            stderr = str(execution.error)

        success = not bool(stderr)
        return ExecutionResult(stdout=stdout, stderr=stderr, success=success)

    def close(self) -> None:
        if self._sandbox is not None:
            self._sandbox.kill()
            self._sandbox = None
