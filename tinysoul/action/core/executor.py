"""Action executor interfaces and registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from tinysoul.runtime import SignalBus

from .call import ActionExecution
from .result import ActionResult


@dataclass(frozen=True)
class ActionExecutionContext:
    """Runtime services available to action executors."""

    services: object | None = None
    signal_bus: SignalBus | None = None


class ActionExecutor(Protocol):
    """Protocol for concrete action executors."""

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        """Execute one action."""
        ...


class ExecutorRegistry:
    """Resolve action executors by backend handler name."""

    def __init__(self) -> None:
        self._executors: dict[str, ActionExecutor] = {}

    def register(self, handler: str, executor: ActionExecutor) -> None:
        if not handler:
            raise ValueError("handler must be non-empty")
        if handler in self._executors:
            raise ValueError(f"Action executor already registered: {handler}")
        self._executors[handler] = executor

    def get(self, handler: str) -> ActionExecutor:
        try:
            return self._executors[handler]
        except KeyError as exc:
            raise KeyError(f"Unknown action executor: {handler}") from exc
