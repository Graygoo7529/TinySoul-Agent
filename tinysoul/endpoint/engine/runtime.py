"""Endpoint runtime status and command engine."""

from __future__ import annotations

from enum import StrEnum
from typing import Generic

from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.loop import LoopControlKind
from tinysoul.loop.errors import LoopError
from tinysoul.runtime import RuntimeGatewayError

from ..errors import EndpointRequestError
from .contracts import EndpointGenerationT
from .context import EndpointEngineContext


class EndpointControlKind(StrEnum):
    STOP_TURN = "stop_turn"
    EXIT_PROGRAM = "exit_program"


class EndpointRuntimeEngine(Generic[EndpointGenerationT]):
    """Translate runtime status and control requests to the App gateway."""

    def __init__(self, context: EndpointEngineContext[EndpointGenerationT]) -> None:
        self._context = context

    def status(self) -> JsonObject:
        turn_scope = self._context.gateway.active_turn_scope
        generation_id = ""
        activity = "idle"
        runtime_handle = self._context.runtime_handle
        if runtime_handle is not None:
            snapshot = runtime_handle.snapshot()
            generation_id = snapshot.generation_id
            activity = snapshot.activity.value
        try:
            with self._context.workspace_lease() as (maintenance, workspace):
                with maintenance.active_day_lease() as day:
                    workspace_revision = workspace.load_manifest().revision
                    active_day = str(day)
        except LoopError:
            workspace_revision = -1
            active_day = ""
        return {
            "protocol_version": 1,
            "instance_id": self._context.settings.instance_id,
            "project_identity": self._context.settings.project_identity,
            "ready": bool(active_day),
            "active_day": active_day,
            "turn_active": turn_scope is not None,
            "runtime": {
                "generation_id": generation_id,
                "activity": activity,
            },
            "workspace_revision": workspace_revision,
            "latest_event_sequence": self._context.events.latest_sequence,
            "event_journal": self._context.events.journal_status(),
        }

    def submit_user_input(
        self,
        text: str,
        metadata: JsonObject,
        *,
        command_id: str = "",
    ) -> JsonObject:
        if not isinstance(text, str) or not text.strip():
            raise EndpointRequestError(
                status_code=422,
                code="input.invalid",
                message="Input text must be non-empty.",
            )
        try:
            receipt = self._context.gateway.submit_user_input(
                text,
                source="endpoint",
                metadata=to_json_object(metadata),
                command_id=command_id or None,
            )
        except RuntimeGatewayError as exc:
            raise EndpointRequestError(
                status_code=409,
                code="input.rejected",
                message=str(exc),
            ) from exc
        return receipt.to_json()

    def submit_control(
        self,
        kind: EndpointControlKind,
        metadata: JsonObject,
        *,
        command_id: str = "",
    ) -> JsonObject:
        loop_kind = {
            EndpointControlKind.STOP_TURN: LoopControlKind.STOP_TURN,
            EndpointControlKind.EXIT_PROGRAM: LoopControlKind.EXIT_PROGRAM,
        }[kind]
        try:
            receipt = self._context.gateway.request_control(
                loop_kind,
                source="endpoint",
                text=kind.value,
                metadata={
                    **to_json_object(metadata),
                    **({"command_id": command_id} if command_id else {}),
                },
            )
        except RuntimeGatewayError as exc:
            raise EndpointRequestError(
                status_code=409,
                code="control.rejected",
                message=str(exc),
            ) from exc
        return receipt.to_json()
