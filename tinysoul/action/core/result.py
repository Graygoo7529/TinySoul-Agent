"""Action local result models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4

from tinysoul.infra.json import JsonObject, to_json_object

from tinysoul.runtime import CyclePhase

from .errors import ActionInvariantError


class ActionResultStatus(StrEnum):
    """Final status for one action execution."""

    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


class ActionResultStage(StrEnum):
    """The stage where an action result was produced."""

    NORMALIZE = "normalize"
    PREPARE = "prepare"
    HOOK = "hook"
    SCHEDULE = "schedule"
    EXECUTE = "execute"
    TIMEOUT = "timeout"


class ActionTraceMode(StrEnum):
    """How an action result should be retained in TurnTrace."""

    STANDARD = "standard"
    FOLDABLE = "foldable"


@dataclass(frozen=True)
class ActionTraceProjection:
    """Optional compact trace form for a large, recall-style action result."""

    mode: ActionTraceMode = ActionTraceMode.STANDARD
    origin_ref: str = ""
    compact_payload: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.mode, ActionTraceMode):
            raise ActionInvariantError(
                "ActionTraceProjection.mode must be an ActionTraceMode"
            )
        if self.mode is ActionTraceMode.FOLDABLE and not self.origin_ref:
            raise ActionInvariantError(
                "Foldable ActionTraceProjection requires a non-empty origin_ref"
            )
        object.__setattr__(
            self,
            "compact_payload",
            to_json_object(self.compact_payload),
        )


class ActionPhaseResultStatus(StrEnum):
    """Status for an action-module phase-level local result."""

    SUCCESS = "success"
    FAILED = "failed"


class ActionPhaseResultStage(StrEnum):
    """The action-module phase stage where a phase-level result was produced."""

    SCOPE = "scope"
    NORMALIZE = "normalize"
    PREPARE = "prepare"
    RUN = "run"


@dataclass(frozen=True)
class ActionResult:
    """A structured local result for one model-side action call."""

    result_id: str
    call_id: str
    action_name: str
    status: ActionResultStatus
    stage: ActionResultStage
    sequence: int
    invoke_id: str | None = None
    batch_id: str | None = None
    domain: str = ""
    payload: JsonObject = field(default_factory=dict)
    model_feedback: str = ""
    frame_data: JsonObject = field(default_factory=dict)
    trace_projection: ActionTraceProjection | None = None

    def __post_init__(self) -> None:
        if not self.result_id:
            raise ActionInvariantError("ActionResult.result_id must be non-empty")
        if not self.call_id:
            raise ActionInvariantError("ActionResult.call_id must be non-empty")
        if not self.action_name:
            raise ActionInvariantError("ActionResult.action_name must be non-empty")
        if not isinstance(self.status, ActionResultStatus):
            raise ActionInvariantError("ActionResult.status must be an ActionResultStatus")
        if not isinstance(self.stage, ActionResultStage):
            raise ActionInvariantError("ActionResult.stage must be an ActionResultStage")
        if self.sequence <= 0:
            raise ActionInvariantError("ActionResult.sequence must be positive")
        if self.trace_projection is not None and not isinstance(
            self.trace_projection,
            ActionTraceProjection,
        ):
            raise ActionInvariantError(
                "ActionResult.trace_projection must be an ActionTraceProjection or None"
            )
        object.__setattr__(self, "payload", to_json_object(self.payload))
        object.__setattr__(self, "frame_data", to_json_object(self.frame_data))

    @classmethod
    def success(
        cls,
        *,
        call_id: str,
        invoke_id: str,
        batch_id: str,
        action_name: str,
        sequence: int,
        domain: str = "",
        payload: JsonObject | None = None,
        model_feedback: str = "",
        frame_data: JsonObject | None = None,
        trace_projection: ActionTraceProjection | None = None,
    ) -> "ActionResult":
        return cls(
            result_id=_result_id(),
            call_id=call_id,
            invoke_id=invoke_id,
            batch_id=batch_id,
            action_name=action_name,
            status=ActionResultStatus.SUCCESS,
            stage=ActionResultStage.EXECUTE,
            sequence=sequence,
            domain=domain,
            payload=payload or {},
            model_feedback=model_feedback,
            frame_data=frame_data or {},
            trace_projection=trace_projection,
        )

    @classmethod
    def failed(
        cls,
        *,
        call_id: str,
        action_name: str,
        stage: ActionResultStage,
        sequence: int,
        model_feedback: str,
        invoke_id: str | None = None,
        batch_id: str | None = None,
        domain: str = "",
        payload: JsonObject | None = None,
        frame_data: JsonObject | None = None,
    ) -> "ActionResult":
        return cls(
            result_id=_result_id(),
            call_id=call_id,
            invoke_id=invoke_id,
            batch_id=batch_id,
            action_name=action_name,
            status=ActionResultStatus.FAILED,
            stage=stage,
            sequence=sequence,
            domain=domain,
            payload=payload or {},
            model_feedback=model_feedback,
            frame_data=frame_data or {},
        )

    @classmethod
    def timeout(
        cls,
        *,
        call_id: str,
        invoke_id: str,
        batch_id: str,
        action_name: str,
        sequence: int,
        model_feedback: str,
        domain: str = "",
        payload: JsonObject | None = None,
        frame_data: JsonObject | None = None,
    ) -> "ActionResult":
        return cls(
            result_id=_result_id(),
            call_id=call_id,
            invoke_id=invoke_id,
            batch_id=batch_id,
            action_name=action_name,
            status=ActionResultStatus.TIMEOUT,
            stage=ActionResultStage.TIMEOUT,
            sequence=sequence,
            domain=domain,
            payload=payload or {},
            model_feedback=model_feedback,
            frame_data=frame_data or {},
        )


def _result_id() -> str:
    return f"action_result_{uuid4().hex[:8]}"


@dataclass(frozen=True)
class ActionPhaseResult:
    """A structured local result for an action-module phase issue."""

    result_id: str
    phase: CyclePhase
    status: ActionPhaseResultStatus
    stage: ActionPhaseResultStage
    payload: JsonObject = field(default_factory=dict)
    model_feedback: str = ""
    frame_data: JsonObject = field(default_factory=dict)
    turn_id: str = ""
    cycle_id: str = ""

    def __post_init__(self) -> None:
        if not self.result_id:
            raise ActionInvariantError("ActionPhaseResult.result_id must be non-empty")
        if not isinstance(self.phase, CyclePhase):
            raise ActionInvariantError("ActionPhaseResult.phase must be a CyclePhase")
        if not isinstance(self.status, ActionPhaseResultStatus):
            raise ActionInvariantError(
                "ActionPhaseResult.status must be an ActionPhaseResultStatus"
            )
        if not isinstance(self.stage, ActionPhaseResultStage):
            raise ActionInvariantError(
                "ActionPhaseResult.stage must be an ActionPhaseResultStage"
            )
        object.__setattr__(self, "payload", to_json_object(self.payload))
        object.__setattr__(self, "frame_data", to_json_object(self.frame_data))

    @classmethod
    def success(
        cls,
        *,
        phase: CyclePhase,
        stage: ActionPhaseResultStage,
        payload: JsonObject | None = None,
        model_feedback: str = "",
        frame_data: JsonObject | None = None,
        turn_id: str = "",
        cycle_id: str = "",
    ) -> "ActionPhaseResult":
        return cls(
            result_id=_phase_result_id(),
            phase=phase,
            status=ActionPhaseResultStatus.SUCCESS,
            stage=stage,
            payload=payload or {},
            model_feedback=model_feedback,
            frame_data=frame_data or {},
            turn_id=turn_id,
            cycle_id=cycle_id,
        )

    @classmethod
    def failed(
        cls,
        *,
        phase: CyclePhase,
        stage: ActionPhaseResultStage,
        model_feedback: str,
        payload: JsonObject | None = None,
        frame_data: JsonObject | None = None,
        turn_id: str = "",
        cycle_id: str = "",
    ) -> "ActionPhaseResult":
        return cls(
            result_id=_phase_result_id(),
            phase=phase,
            status=ActionPhaseResultStatus.FAILED,
            stage=stage,
            payload=payload or {},
            model_feedback=model_feedback,
            frame_data=frame_data or {},
            turn_id=turn_id,
            cycle_id=cycle_id,
        )


def _phase_result_id() -> str:
    return f"action_phase_result_{uuid4().hex[:8]}"
