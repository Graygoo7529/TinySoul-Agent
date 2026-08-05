"""Action executor interfaces and registry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Event, Lock
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
    _cancel_callbacks: list[Callable[[str], None]] = field(
        default_factory=list,
        init=False,
        repr=False,
    )
    _cancel_lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def remaining_seconds(self) -> float | None:
        if self.deadline is None:
            return None
        return max(0.0, self.deadline - monotonic())

    def is_expired(self) -> bool:
        return self.deadline is not None and monotonic() >= self.deadline

    def request_cancel(self, reason: str) -> None:
        callbacks: tuple[Callable[[str], None], ...]
        with self._cancel_lock:
            if self.cancel_event.is_set():
                return
            self.cancel_reason = reason or "cancelled"
            self.cancel_event.set()
            callbacks = tuple(self._cancel_callbacks)
            self._cancel_callbacks.clear()
        for callback in callbacks:
            try:
                callback(self.cancel_reason)
            except Exception:
                # Cancellation cleanup must not replace the controlling transfer.
                continue

    def add_cancel_callback(self, callback: Callable[[str], None]) -> None:
        """Run callback when cancellation is requested, or immediately if cancelled."""

        reason = ""
        with self._cancel_lock:
            if self.cancel_event.is_set():
                reason = self.cancel_reason or "cancelled"
            else:
                self._cancel_callbacks.append(callback)
        if reason:
            callback(reason)

    def remove_cancel_callback(self, callback: Callable[[str], None]) -> None:
        with self._cancel_lock:
            if callback in self._cancel_callbacks:
                self._cancel_callbacks.remove(callback)

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
    # Owner-provided cooperative cancel poll (e.g. a Turn cancel token).
    # The batch runner converts it into per-execution cancel requests.
    cancelled: Callable[[], bool] | None = None


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
