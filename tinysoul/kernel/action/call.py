"""Action call and execution input models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from time import monotonic

from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.runtime import RunScope

from .errors import ActionInvariantError
from tinysoul.runtime import CyclePhase
from .result import ActionPhaseResult, ActionResult
from .catalog.specs import ActionSpec


@dataclass(frozen=True)
class ActionCall:
    """A normalized Phase2 action call."""

    call_id: str
    action_name: str
    params: JsonObject
    sequence: int

    def __post_init__(self) -> None:
        _require_non_empty(self.call_id, "ActionCall.call_id")
        _require_non_empty(self.action_name, "ActionCall.action_name")
        if self.sequence <= 0:
            raise ActionInvariantError("ActionCall.sequence must be positive")
        object.__setattr__(self, "params", to_json_object(self.params))


@dataclass(frozen=True)
class ActionFramework:
    """Framework-only execution data for an action call."""

    invoke_id: str
    batch_id: str
    scope: RunScope
    domain: str
    deadline: float | None = None
    timeout_seconds: float | None = None
    turn_id: str = ""
    cycle_id: str = ""
    phase: CyclePhase = CyclePhase.PHASE3

    def __post_init__(self) -> None:
        _require_non_empty(self.invoke_id, "ActionFramework.invoke_id")
        _require_non_empty(self.batch_id, "ActionFramework.batch_id")
        _require_non_empty(self.domain, "ActionFramework.domain")
        if not isinstance(self.scope, RunScope):
            raise ActionInvariantError("ActionFramework.scope must be a RunScope")
        if not isinstance(self.phase, CyclePhase):
            raise ActionInvariantError("ActionFramework.phase must be a CyclePhase")
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ActionInvariantError(
                "ActionFramework.timeout_seconds must be positive"
            )

    def is_expired(self) -> bool:
        return self.deadline is not None and monotonic() >= self.deadline


@dataclass(frozen=True)
class ActionExecution:
    """A Phase3 execution wrapper around an action call."""

    action: ActionSpec
    call: ActionCall
    framework: ActionFramework

    def __post_init__(self) -> None:
        if not isinstance(self.action, ActionSpec):
            raise ActionInvariantError("ActionExecution.action must be an ActionSpec")
        if self.action.name != self.call.action_name:
            raise ActionInvariantError(
                "ActionExecution.action.name must match ActionCall.action_name"
            )
        if self.action.domain != self.framework.domain:
            raise ActionInvariantError(
                "ActionExecution.action.domain must match ActionFramework.domain"
            )


@dataclass(frozen=True)
class ActionBatch:
    """A batch of action executions scheduled together."""

    batch_id: str
    executions: tuple[ActionExecution, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _require_non_empty(self.batch_id, "ActionBatch.batch_id")
        seen_call_ids: set[str] = set()
        seen_invoke_ids: set[str] = set()
        seen_sequences: set[int] = set()
        for execution in self.executions:
            if execution.framework.batch_id != self.batch_id:
                raise ActionInvariantError(
                    "ActionExecution.framework.batch_id must match ActionBatch.batch_id"
                )
            if execution.call.call_id in seen_call_ids:
                raise ActionInvariantError(
                    f"Duplicate action call id in batch: {execution.call.call_id}"
                )
            if execution.framework.invoke_id in seen_invoke_ids:
                raise ActionInvariantError(
                    f"Duplicate action invoke id in batch: {execution.framework.invoke_id}"
                )
            if execution.call.sequence in seen_sequences:
                raise ActionInvariantError(
                    f"Duplicate action sequence in batch: {execution.call.sequence}"
                )
            seen_call_ids.add(execution.call.call_id)
            seen_invoke_ids.add(execution.framework.invoke_id)
            seen_sequences.add(execution.call.sequence)


class ExecutionState(StrEnum):
    REQUESTED = "requested"
    STARTED = "started"
    SETTLED = "settled"
    CANCELLED = "cancelled"
    NOT_EXECUTED = "not_executed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ExecutionFact:
    """Typed execution fact; interrupted work need not have a tool result."""

    call: ActionCall
    framework: ActionFramework
    state: ExecutionState
    result: ActionResult | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.call, ActionCall) or not isinstance(
            self.framework, ActionFramework
        ):
            raise ActionInvariantError("Execution fact requires typed call identity")
        if not isinstance(self.state, ExecutionState):
            raise ActionInvariantError("Execution fact requires a typed state")
        if (self.state is ExecutionState.SETTLED) != (self.result is not None):
            raise ActionInvariantError("Only settled execution facts contain a result")
        if self.result is not None and (
            self.result.invoke_id != self.framework.invoke_id
            or self.result.call_id != self.call.call_id
            or self.result.batch_id != self.framework.batch_id
            or self.result.action_name != self.call.action_name
            or self.result.sequence != self.call.sequence
            or self.result.domain != self.framework.domain
        ):
            raise ActionInvariantError("Execution fact result identity does not match")


@dataclass(frozen=True)
class ActionNormalization:
    """Normalized Phase2 action calls plus local normalization failures."""

    calls: tuple[ActionCall, ...] = field(default_factory=tuple)
    results: tuple[ActionResult, ...] = field(default_factory=tuple)

    def merged_results(
        self,
        execution_results: tuple[ActionResult, ...],
    ) -> tuple[ActionResult, ...]:
        """Return normalization and execution results in original call order."""

        return tuple(
            sorted(
                (*self.results, *execution_results),
                key=lambda result: result.sequence,
            )
        )


@dataclass(frozen=True)
class ActionBatchPreparation:
    """Prepared action batch plus local preparation results."""

    batch: ActionBatch
    results: tuple[ActionResult, ...] = field(default_factory=tuple)
    phase_results: tuple[ActionPhaseResult, ...] = field(default_factory=tuple)


def _require_non_empty(value: str, field: str) -> None:
    if not value:
        raise ActionInvariantError(f"{field} must be non-empty")
