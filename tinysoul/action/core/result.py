"""Action execution result models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from tinysoul.infra.json import JsonObject, to_json_object


class ActionResultStatus(StrEnum):
    """Final status for one action execution."""

    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


class ActionResultStage(StrEnum):
    """The stage where an action result was produced."""

    NORMALIZE = "normalize"
    HOOK = "hook"
    EXECUTE = "execute"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class ActionResult:
    """A structured result for one action execution."""

    invoke_id: str
    action_name: str
    status: ActionResultStatus
    stage: ActionResultStage
    payload: JsonObject = field(default_factory=dict)
    model_feedback: str = ""
    frame_data: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.invoke_id:
            raise ValueError("ActionResult.invoke_id must be non-empty")
        if not self.action_name:
            raise ValueError("ActionResult.action_name must be non-empty")
        if not isinstance(self.status, ActionResultStatus):
            raise TypeError("ActionResult.status must be an ActionResultStatus")
        if not isinstance(self.stage, ActionResultStage):
            raise TypeError("ActionResult.stage must be an ActionResultStage")
        object.__setattr__(self, "payload", to_json_object(self.payload))
        object.__setattr__(self, "frame_data", to_json_object(self.frame_data))

    @classmethod
    def success(
        cls,
        *,
        invoke_id: str,
        action_name: str,
        payload: JsonObject | None = None,
        model_feedback: str = "",
        frame_data: JsonObject | None = None,
    ) -> "ActionResult":
        return cls(
            invoke_id=invoke_id,
            action_name=action_name,
            status=ActionResultStatus.SUCCESS,
            stage=ActionResultStage.EXECUTE,
            payload=payload or {},
            model_feedback=model_feedback,
            frame_data=frame_data or {},
        )

    @classmethod
    def failed(
        cls,
        *,
        invoke_id: str,
        action_name: str,
        stage: ActionResultStage,
        model_feedback: str,
        payload: JsonObject | None = None,
        frame_data: JsonObject | None = None,
    ) -> "ActionResult":
        return cls(
            invoke_id=invoke_id,
            action_name=action_name,
            status=ActionResultStatus.FAILED,
            stage=stage,
            payload=payload or {},
            model_feedback=model_feedback,
            frame_data=frame_data or {},
        )

    @classmethod
    def timeout(
        cls,
        *,
        invoke_id: str,
        action_name: str,
        model_feedback: str,
        payload: JsonObject | None = None,
        frame_data: JsonObject | None = None,
    ) -> "ActionResult":
        return cls(
            invoke_id=invoke_id,
            action_name=action_name,
            status=ActionResultStatus.TIMEOUT,
            stage=ActionResultStage.TIMEOUT,
            payload=payload or {},
            model_feedback=model_feedback,
            frame_data=frame_data or {},
        )
