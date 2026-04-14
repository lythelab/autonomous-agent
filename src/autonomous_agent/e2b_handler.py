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

        try:
            return create(**kwargs)
        except TypeError:
            # Support older SDK signatures by retrying with fewer kwargs.
            if "metadata" in kwargs:
                kwargs.pop("metadata")
                try:
                    return create(**kwargs)
                except TypeError:
                    pass
            if "template" in kwargs:
                kwargs.pop("template")
                return create(**kwargs)
            raise

    @staticmethod
    def close_sandbox(sandbox: Any) -> None:
        close = getattr(sandbox, "close", None)
        if callable(close):
            close()
