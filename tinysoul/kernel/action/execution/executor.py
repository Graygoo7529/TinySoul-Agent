"""Action executor interfaces and registry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Event, Lock
from time import monotonic
from typing import Protocol
from tinysoul.infra.concurrency import JoinedOperations

from tinysoul.runtime import RuntimeModuleRunner, SignalBus

from ..call import ActionExecution, ExecutionFact
from ..catalog.catalog import ActionCatalog
from ..errors import ActionContractError
from ..result import ActionResult


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
    record_execution: Callable[[ExecutionFact], None] | None = None
    owner_operations: JoinedOperations = field(default_factory=JoinedOperations)

    def require_signal_bus(self) -> SignalBus:
        if self.signal_bus is None:
            raise ActionContractError("This Action requires an owner update channel")
        return self.signal_bus


class ActionExecutor(Protocol):
    """Protocol for concrete action executors."""

    async def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        """Execute one action."""
        ...


class ExecutorRegistry:
    """Resolve action executors by their explicit executor identity."""

    def __init__(self) -> None:
        self._executors: dict[str, ActionExecutor] = {}

    def register(self, executor_id: str, executor: ActionExecutor) -> None:
        if not executor_id:
            raise ActionContractError("executor_id must be non-empty")
        if executor_id in self._executors:
            raise ActionContractError(
                f"Action executor already registered: {executor_id}"
            )
        self._executors[executor_id] = executor

    def get(self, executor_id: str) -> ActionExecutor:
        try:
            return self._executors[executor_id]
        except KeyError as exc:
            raise ActionContractError(
                f"Unknown action executor: {executor_id}"
            ) from exc

    def has(self, executor_id: str) -> bool:
        return executor_id in self._executors

    def missing_executors_for(self, catalog: ActionCatalog) -> tuple[str, ...]:
        missing = {
            action.execution.executor
            for action in catalog.actions()
            if not self.has(action.execution.executor)
        }
        return tuple(sorted(missing))

    def validate_catalog(self, catalog: ActionCatalog) -> None:
        missing = self.missing_executors_for(catalog)
        if missing:
            raise ActionContractError(
                "Action catalog references unregistered executors: "
                + ", ".join(missing)
            )
