"""Action local result models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4

from tinysoul.infra.json import JsonObject, dumps_json, to_json_object
from tinysoul.runtime import CyclePhase

from .errors import ActionInvariantError


_FAILURE_IDENTIFIER_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyz0123456789._-"
)
_MAX_FAILURE_FEEDBACK_CHARS = 2000
_MAX_FAILURE_CONSTRAINT_CHARS = 4000


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


class ActionFailureDisposition(StrEnum):
    """Stable recovery direction for one action-local failure."""

    RETRY_SAME = "retry_same"
    CHANGE_REQUEST = "change_request"
    USE_FALLBACK = "use_fallback"
    STOP = "stop"


class ActionTraceMode(StrEnum):
    """How an action result should be retained in TurnTrace."""

    STANDARD = "standard"
    FOLDABLE = "foldable"


@dataclass(frozen=True)
class ActionLocalFailure:
    """Canonical model-visible failure facts for one local action result."""

    reason: str
    scope: str
    disposition: ActionFailureDisposition
    feedback: str
    constraint: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_failure_identifier(self.reason, label="reason")
        _validate_failure_identifier(self.scope, label="scope")
        if not isinstance(self.disposition, ActionFailureDisposition):
            raise ActionInvariantError(
                "ActionLocalFailure.disposition must be an ActionFailureDisposition"
            )
        if not isinstance(self.feedback, str) or not self.feedback.strip():
            raise ActionInvariantError(
                "ActionLocalFailure.feedback must be a non-empty string"
            )
        if len(self.feedback) > _MAX_FAILURE_FEEDBACK_CHARS:
            raise ActionInvariantError(
                "ActionLocalFailure.feedback exceeds its character limit"
            )
        constraint = to_json_object(self.constraint)
        if len(dumps_json(constraint)) > _MAX_FAILURE_CONSTRAINT_CHARS:
            raise ActionInvariantError(
                "ActionLocalFailure.constraint exceeds its character limit"
            )
        object.__setattr__(self, "constraint", constraint)

    def to_json(self) -> JsonObject:
        value: JsonObject = {
            "reason": self.reason,
            "scope": self.scope,
            "disposition": self.disposition.value,
            "feedback": self.feedback,
        }
        if self.constraint:
            value["constraint"] = self.constraint
        return value

    @classmethod
    def from_json(cls, value: object) -> "ActionLocalFailure":
        if not isinstance(value, dict):
            raise ActionInvariantError("Action failure envelope must be an object")
        if set(value) - {"reason", "scope", "disposition", "feedback", "constraint"}:
            raise ActionInvariantError("Action failure envelope contains unknown fields")
        reason = value.get("reason")
        scope = value.get("scope")
        feedback = value.get("feedback")
        disposition_value = value.get("disposition")
        if not isinstance(reason, str) or not isinstance(scope, str):
            raise ActionInvariantError(
                "Action failure envelope requires string reason and scope"
            )
        if not isinstance(feedback, str):
            raise ActionInvariantError(
                "Action failure envelope requires string feedback"
            )
        try:
            disposition = ActionFailureDisposition(disposition_value)
        except (TypeError, ValueError) as exc:
            raise ActionInvariantError(
                "Action failure envelope has an invalid disposition"
            ) from exc
        constraint = value.get("constraint", {})
        if not isinstance(constraint, dict):
            raise ActionInvariantError(
                "Action failure envelope constraint must be an object"
            )
        return cls(
            reason=reason,
            scope=scope,
            disposition=disposition,
            feedback=feedback,
            constraint=to_json_object(constraint),
        )


@dataclass(frozen=True)
class ActionResultEnvelope:
    """Stable model/canonical projection of an ActionResult."""

    action_name: str
    status: ActionResultStatus
    stage: ActionResultStage
    payload: JsonObject = field(default_factory=dict)
    failure: ActionLocalFailure | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.action_name, str) or not self.action_name:
            raise ActionInvariantError(
                "ActionResultEnvelope.action_name must be non-empty"
            )
        if not isinstance(self.status, ActionResultStatus):
            raise ActionInvariantError(
                "ActionResultEnvelope.status must be an ActionResultStatus"
            )
        if not isinstance(self.stage, ActionResultStage):
            raise ActionInvariantError(
                "ActionResultEnvelope.stage must be an ActionResultStage"
            )
        _validate_failure_status(self.status, self.failure, owner="ActionResultEnvelope")
        object.__setattr__(self, "payload", to_json_object(self.payload))

    def to_json(self) -> JsonObject:
        value: JsonObject = {
            "action": self.action_name,
            "status": self.status.value,
            "stage": self.stage.value,
        }
        if self.failure is not None:
            value["failure"] = self.failure.to_json()
        if self.payload:
            value["payload"] = self.payload
        return value

    @classmethod
    def from_json(cls, value: object) -> "ActionResultEnvelope":
        if not isinstance(value, dict):
            raise ActionInvariantError("Action result envelope must be an object")
        if set(value) - {"action", "status", "stage", "payload", "failure"}:
            raise ActionInvariantError(
                "Action result envelope contains unknown fields"
            )
        action_name = value.get("action")
        if not isinstance(action_name, str):
            raise ActionInvariantError("Action result envelope requires string action")
        try:
            status = ActionResultStatus(value.get("status"))
            stage = ActionResultStage(value.get("stage"))
        except (TypeError, ValueError) as exc:
            raise ActionInvariantError(
                "Action result envelope has an invalid status or stage"
            ) from exc
        payload = value.get("payload", {})
        if not isinstance(payload, dict):
            raise ActionInvariantError("Action result envelope payload must be an object")
        failure_value = value.get("failure")
        failure = (
            ActionLocalFailure.from_json(failure_value)
            if failure_value is not None
            else None
        )
        return cls(
            action_name=action_name,
            status=status,
            stage=stage,
            payload=to_json_object(payload),
            failure=failure,
        )


@dataclass(frozen=True)
class ActionTraceProjection:
    """Business-provided canonical payload for a foldable action result."""

    origin_refs: tuple[str, ...] = ()
    canonical_payload: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.origin_refs, tuple):
            raise ActionInvariantError(
                "ActionTraceProjection.origin_refs must be a tuple"
            )
        if any(not isinstance(ref, str) or not ref for ref in self.origin_refs):
            raise ActionInvariantError(
                "ActionTraceProjection.origin_refs must contain non-empty strings"
            )
        if len(set(self.origin_refs)) != len(self.origin_refs):
            raise ActionInvariantError(
                "ActionTraceProjection.origin_refs must be unique"
            )
        canonical_payload = to_json_object(self.canonical_payload)
        if not canonical_payload:
            raise ActionInvariantError(
                "ActionTraceProjection.canonical_payload must be non-empty"
            )
        object.__setattr__(self, "canonical_payload", canonical_payload)


class ActionPhaseResultStage(StrEnum):
    """The action-module phase stage where a phase failure was produced."""

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
    failure: ActionLocalFailure | None = None
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
        _validate_failure_status(self.status, self.failure, owner="ActionResult")
        if self.trace_projection is not None and not isinstance(
            self.trace_projection,
            ActionTraceProjection,
        ):
            raise ActionInvariantError(
                "ActionResult.trace_projection must be an ActionTraceProjection or None"
            )
        if (
            self.status is not ActionResultStatus.SUCCESS
            and self.trace_projection is not None
        ):
            raise ActionInvariantError(
                "Only successful ActionResults may carry a trace projection"
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
        failure: ActionLocalFailure,
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
            failure=failure,
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
        failure: ActionLocalFailure,
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
            failure=failure,
            frame_data=frame_data or {},
        )

    def envelope(self, *, payload: JsonObject | None = None) -> ActionResultEnvelope:
        return ActionResultEnvelope(
            action_name=self.action_name,
            status=self.status,
            stage=self.stage,
            payload=self.payload if payload is None else payload,
            failure=self.failure,
        )


@dataclass(frozen=True)
class ActionPhaseResult:
    """A local Action module failure that cannot bind to one action call."""

    result_id: str
    phase: CyclePhase
    stage: ActionPhaseResultStage
    failure: ActionLocalFailure
    frame_data: JsonObject = field(default_factory=dict)
    turn_id: str = ""
    cycle_id: str = ""

    def __post_init__(self) -> None:
        if not self.result_id:
            raise ActionInvariantError("ActionPhaseResult.result_id must be non-empty")
        if not isinstance(self.phase, CyclePhase):
            raise ActionInvariantError("ActionPhaseResult.phase must be a CyclePhase")
        if not isinstance(self.stage, ActionPhaseResultStage):
            raise ActionInvariantError(
                "ActionPhaseResult.stage must be an ActionPhaseResultStage"
            )
        if not isinstance(self.failure, ActionLocalFailure):
            raise ActionInvariantError(
                "ActionPhaseResult.failure must be an ActionLocalFailure"
            )
        object.__setattr__(self, "frame_data", to_json_object(self.frame_data))

    @classmethod
    def failed(
        cls,
        *,
        phase: CyclePhase,
        stage: ActionPhaseResultStage,
        failure: ActionLocalFailure,
        frame_data: JsonObject | None = None,
        turn_id: str = "",
        cycle_id: str = "",
    ) -> "ActionPhaseResult":
        return cls(
            result_id=_phase_result_id(),
            phase=phase,
            stage=stage,
            failure=failure,
            frame_data=frame_data or {},
            turn_id=turn_id,
            cycle_id=cycle_id,
        )


def _validate_failure_status(
    status: ActionResultStatus,
    failure: ActionLocalFailure | None,
    *,
    owner: str,
) -> None:
    if status is ActionResultStatus.SUCCESS and failure is not None:
        raise ActionInvariantError(f"{owner} success cannot carry a failure")
    if status is not ActionResultStatus.SUCCESS and not isinstance(
        failure,
        ActionLocalFailure,
    ):
        raise ActionInvariantError(f"{owner} failed/timeout requires a failure")


def _validate_failure_identifier(value: str, *, label: str) -> None:
    if not isinstance(value, str) or not value:
        raise ActionInvariantError(
            f"ActionLocalFailure.{label} must be a non-empty string"
        )
    if len(value) > 160 or any(char not in _FAILURE_IDENTIFIER_CHARS for char in value):
        raise ActionInvariantError(
            f"ActionLocalFailure.{label} must be a stable lowercase identifier"
        )


def _result_id() -> str:
    return f"action_result_{uuid4().hex[:8]}"


def _phase_result_id() -> str:
    return f"action_phase_result_{uuid4().hex[:8]}"
