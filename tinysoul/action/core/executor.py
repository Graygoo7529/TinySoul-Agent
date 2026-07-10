"""Action executor interfaces and registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event
from time import monotonic
from typing import Protocol

from tinysoul.runtime import RuntimeModuleRunner, SignalBus

from .call import ActionExecution
from .catalog import ActionCatalog
from .errors import ActionContractError
from .result import ActionResult


@dataclass
class ActionExecutionControl:
    """Per-action execution control used by cooperative executors."""

    deadline: float | None = None
    cancel_event: Event = field(default_factory=Event)
    cancel_reason: str = ""

    def remaining_seconds(self) -> float | None:
        if self.deadline is None:
            return None
        return max(0.0, self.deadline - monotonic())

    def is_expired(self) -> bool:
        return self.deadline is not None and monotonic() >= self.deadline

    def request_cancel(self, reason: str) -> None:
        if not self.cancel_reason:
            self.cancel_reason = reason
        self.cancel_event.set()

    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def check_cancelled(self) -> None:
        if self.is_cancelled() or self.is_expired():
            reason = self.cancel_reason or "deadline_expired"
            raise ActionExecutionCancelled(reason)


class ActionExecutionCancelled(Exception):
    """Raised by cooperative executors when an action should stop."""


@dataclass(frozen=True)
class ActionExecutionContext:
    """Runtime services available to action executors."""

    control: ActionExecutionControl = field(default_factory=ActionExecutionControl)
    signal_bus: SignalBus | None = None
    module_runner: RuntimeModuleRunner | None = None


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
            raise ActionContractError("handler must be non-empty")
        if handler in self._executors:
            raise ActionContractError(f"Action executor already registered: {handler}")
        self._executors[handler] = executor

    def get(self, handler: str) -> ActionExecutor:
        try:
            return self._executors[handler]
        except KeyError as exc:
            raise ActionContractError(f"Unknown action executor: {handler}") from exc

    def has(self, handler: str) -> bool:
        return handler in self._executors

    def missing_handlers_for(self, catalog: ActionCatalog) -> tuple[str, ...]:
        missing = {
            action.backend.handler
            for action in catalog.actions()
            if not self.has(action.backend.handler)
        }
        return tuple(sorted(missing))

    def validate_catalog(self, catalog: ActionCatalog) -> None:
        missing = self.missing_handlers_for(catalog)
        if missing:
            raise ActionContractError(
                "Action catalog references unregistered executors: "
                + ", ".join(missing)
            )
