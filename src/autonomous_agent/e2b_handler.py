from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

try:
    from e2b_code_interpreter import Sandbox
except ImportError:  # pragma: no cover - optional dependency for local test runs
    Sandbox = None


@dataclass(frozen=True)
class E2BHandlerConfig:
    api_key: str | None
    template: str | None = None
    metadata: dict[str, str] | None = None
    timeout_seconds: int | None = None
    require_sandbox: bool = False


class E2BHandler:
    """Factory and lifecycle helpers for E2B sandbox sessions."""

    def __init__(self, config: E2BHandlerConfig) -> None:
        self.config = config

    def create_sandbox(self) -> Any:
        if Sandbox is None:
            raise RuntimeError("e2b-code-interpreter is not installed")

        if not self.config.api_key:
            raise RuntimeError("E2B_API_KEY is not configured")

        os.environ.setdefault("E2B_API_KEY", self.config.api_key)

        create = getattr(Sandbox, "create", None)
        if create is None:
            raise RuntimeError("Installed E2B Sandbox class does not expose create()")

        kwargs: dict[str, Any] = {}
        if self.config.template:
            kwargs["template"] = self.config.template
        if self.config.metadata:
            kwargs["metadata"] = self.config.metadata
        if self.config.timeout_seconds is not None:
            kwargs["timeout"] = self.config.timeout_seconds

        try:
            sandbox = create(**kwargs)
        except TypeError:
            # Support older SDK signatures by retrying with fewer kwargs.
            for key in ("metadata", "timeout", "template"):
                if key not in kwargs:
                    continue
                kwargs.pop(key)
                try:
                    sandbox = create(**kwargs)
                    break
                except TypeError:
                    continue
            else:
                raise

        if self.config.timeout_seconds is not None:
            set_timeout = getattr(sandbox, "set_timeout", None)
            if callable(set_timeout):
                try:
                    set_timeout(self.config.timeout_seconds)
                except TypeError:
                    # Some SDK versions expose a no-arg or different timeout signature.
                    pass

        return sandbox

    @staticmethod
    def close_sandbox(sandbox: Any) -> None:
        close = getattr(sandbox, "close", None)
        if callable(close):
            close()
