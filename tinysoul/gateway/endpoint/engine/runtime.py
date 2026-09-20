"""Endpoint runtime status and command engine."""

from __future__ import annotations

from enum import StrEnum

from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.kernel.loop import LoopControlKind
from tinysoul.kernel.loop.interaction.inbox import InboxReceipt
from tinysoul.plugins.reflection import ReflectionScope, ReflectionRequest, ReflectionTrigger
from tinysoul.agent.requests import UserTurnRequest
from uuid import uuid4
from tinysoul.infra.time import CalendarDay, CalendarDayError
from tinysoul.runtime import RuntimeGatewayError

from ..errors import EndpointRequestError
from .context import EndpointEngineContext


class EndpointControlKind(StrEnum):
    STOP_TURN = "stop_turn"
    EXIT_PROGRAM = "exit_program"


class EndpointRuntimeEngine:
    """Translate runtime status and control requests to the App gateway."""

    def __init__(self, context: EndpointEngineContext) -> None:
        self._context = context

    async def status(self) -> JsonObject:
        turn_scope = self._context.gateway.active_turn_scope
        runtime = self._context.services.runtime_status()
        active_day = runtime["active_day"]
        return {
            "protocol_version": 2,
            "instance_id": self._context.settings.instance_id,
            "project_identity": self._context.settings.project_identity,
            "ready": bool(active_day),
            "active_day": active_day,
            "turn_active": turn_scope is not None,
            "runtime": runtime,
            "latest_event_sequence": self._context.events.latest_sequence,
            "event_journal": self._context.events.journal_status(),
        }

    async def submit_user_input(
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
            receipt = await self._context.gateway.submit_user_input(
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

    async def create_turn(
        self,
        *,
        kind: str,
        text: str,
        target_day: str,
        instructions: str,
        metadata: JsonObject,
        command_id: str = "",
    ) -> JsonObject:
        identity = command_id or f"command_{uuid4().hex}"
        request: UserTurnRequest | ReflectionRequest
        if kind == "user":
            if not text.strip():
                raise EndpointRequestError(
                    status_code=422, code="turn.text_required", message="User Turn requires text."
                )
            if target_day or instructions:
                raise EndpointRequestError(
                    status_code=422, code="turn.fields_invalid",
                    message="User Turn accepts text, not Reflection fields.",
                )
            request = UserTurnRequest(
                text, source="endpoint", metadata=metadata, request_id=identity
            )
        else:
            if kind not in {"home", "memory"} or text:
                raise EndpointRequestError(
                    status_code=422, code="turn.fields_invalid",
                    message="Reflection Turn requires home/memory and instructions.",
                )
            request = ReflectionRequest(
                scope=ReflectionScope(kind), trigger=ReflectionTrigger.MANUAL,
                target_day=_parse_target_day(kind, target_day), instructions=instructions,
                source="endpoint", metadata=metadata, request_id=identity,
            )
        handle = await self._context.gateway.commands.submit_turn(request)
        return {"accepted": True, "command_id": identity, "turn_id": handle.turn_id,
                "kind": kind, "state": handle.state.value}

    async def get_turn(self, turn_id: str) -> JsonObject:
        snapshot = self._context.services.turn_snapshot(turn_id)
        if snapshot is None:
            raise EndpointRequestError(
                status_code=404, code="turn.not_found", message="Turn was not found."
            )
        return snapshot.to_json()

    async def append_input(self, turn_id: str, text: str, input_id: str) -> JsonObject:
        receipt = await self._context.gateway.commands.append_input(turn_id, text, input_id=input_id)
        return _receipt_json(receipt)

    async def reply(self, turn_id: str, question_id: str, response: str) -> JsonObject:
        receipt = await self._context.gateway.commands.reply(turn_id, question_id, response)
        return _receipt_json(receipt)

    async def grant(self, turn_id: str, request_id: str, count: int) -> JsonObject:
        accepted = await self._context.gateway.commands.grant_cycles(turn_id, request_id, count)
        return {"turn_id": turn_id, "request_id": request_id, "accepted": accepted}

    async def cancel(self, turn_id: str) -> JsonObject:
        accepted = await self._context.gateway.commands.cancel_turn(turn_id)
        return {"turn_id": turn_id, "accepted": accepted}

    async def jobs(self, turn_id: str) -> JsonObject:
        jobs = self._context.services.turn_jobs(turn_id)
        if jobs is None:
            raise EndpointRequestError(
                status_code=404, code="turn.not_found", message="Turn was not found."
            )
        return {"turn_id": turn_id, "jobs": [item.to_json() for item in jobs]}

    async def stop_job(self, turn_id: str, job_id: str) -> JsonObject:
        if self._context.services.turn_jobs(turn_id) is None:
            raise EndpointRequestError(
                status_code=404, code="turn.not_found", message="Turn was not found."
            )
        snapshot = await self._context.services.stop_job(turn_id, job_id)
        return snapshot.to_json()

    async def submit_control(
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
            receipt = await self._context.gateway.request_control(
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


def _parse_target_day(kind: str, target_day: str) -> CalendarDay | None:
    if kind == "home" and target_day:
        raise EndpointRequestError(
            status_code=422,
            code="turn.target_day_invalid",
            message="Home Turn does not accept target_day.",
        )
    if kind == "memory" and not target_day:
        raise EndpointRequestError(
            status_code=422,
            code="turn.target_day_required",
            message="Memory Turn requires target_day.",
        )
    if not target_day:
        return None
    try:
        return CalendarDay.parse(target_day)
    except CalendarDayError as exc:
        raise EndpointRequestError(
            status_code=422,
            code="turn.target_day_invalid",
            message="target_day must use YYYY-MM-DD.",
        ) from exc


def _receipt_json(receipt: InboxReceipt) -> JsonObject:
    return {
        "sequence": receipt.sequence,
        "record_id": receipt.record_id,
        "accepted": receipt.accepted,
    }
