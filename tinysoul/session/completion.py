"""Project one typed Context completion into immutable Session business facts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

from tinysoul.action import ActionInvariantError, ActionResultEnvelope
from tinysoul.context import ContextTurnCompletion
from tinysoul.infra.json import JsonObject
from tinysoul.llm.messages import AssistantMessage, JsonPart, ToolResultMessage
from tinysoul.llm.tools import ToolKind, ToolResultStatus
from tinysoul.loop.day import BusinessDay
from tinysoul.runtime import CyclePhase

from .errors import SessionInvariantError
from .models import (
    SessionActionOutcome,
    SessionActionRecord,
    SessionInputRecord,
    SessionOutputRecord,
    SessionTurnRecord,
)


@dataclass(frozen=True)
class _ActionCall:
    call_id: str
    action: str
    request: JsonObject
    order: int


@dataclass(frozen=True)
class _ActionResult:
    call_id: str
    action: str
    envelope: ActionResultEnvelope
    references: tuple[str, ...]


def project_turn_record(
    completion: ContextTurnCompletion,
    *,
    day: BusinessDay,
    output: SessionOutputRecord | None,
    exhausted: bool,
) -> SessionTurnRecord:
    """Validate Action pairing once and create the sole persistent Turn record."""

    calls = _action_calls(completion)
    results = _action_results(completion)
    calls_by_id = _unique_by_id(calls, owner="call")
    results_by_id = _unique_by_id(results, owner="result")
    if set(calls_by_id) != set(results_by_id):
        raise SessionInvariantError(
            "Completed Turn contains unpaired Action calls or results"
        )
    actions: list[SessionActionRecord] = []
    for call in sorted(calls, key=lambda item: item.order):
        result = results_by_id[call.call_id]
        if call.action != result.action or call.action != result.envelope.action_name:
            raise SessionInvariantError(
                f"Completed Turn Action name mismatch: {call.call_id}"
            )
        try:
            outcome = SessionActionOutcome(result.envelope.status.value)
        except ValueError as exc:
            raise SessionInvariantError(
                f"Completed Turn Action outcome is invalid: {call.call_id}"
            ) from exc
        actions.append(
            SessionActionRecord(
                action=call.action,
                request=call.request,
                outcome=outcome,
                result=result.envelope.payload,
                failure=result.envelope.failure,
                references=result.references,
            )
        )
    return SessionTurnRecord(
        ref=f"session:turn/{completion.turn_id}",
        day=str(day),
        inputs=tuple(
            SessionInputRecord(text=item.text, received_at=item.received_at)
            for item in completion.inputs
        ),
        working=completion.working,
        background_links=completion.background_links,
        output=output,
        exhausted=exhausted,
        actions=tuple(actions),
    )


def _action_calls(completion: ContextTurnCompletion) -> tuple[_ActionCall, ...]:
    values: list[_ActionCall] = []
    order = 0
    for entry in completion.trace.entries:
        message = entry.message
        if entry.phase is not CyclePhase.PHASE2 or not isinstance(
            message, AssistantMessage
        ):
            continue
        for call in message.tool_calls:
            if call.kind is not ToolKind.ACTION:
                continue
            values.append(
                _ActionCall(
                    call_id=call.id,
                    action=call.name,
                    request=call.arguments,
                    order=order,
                )
            )
            order += 1
    return tuple(values)


def _action_results(completion: ContextTurnCompletion) -> tuple[_ActionResult, ...]:
    values: list[_ActionResult] = []
    for entry in completion.trace.entries:
        message = entry.message
        if entry.phase is not CyclePhase.PHASE3 or not isinstance(
            message, ToolResultMessage
        ):
            continue
        json_parts = [part.value for part in message.parts if isinstance(part, JsonPart)]
        if len(json_parts) != 1:
            raise SessionInvariantError(
                f"Completed Turn Action result is ambiguous: {message.call_id}"
            )
        try:
            envelope = ActionResultEnvelope.from_json(json_parts[0])
        except ActionInvariantError as exc:
            raise SessionInvariantError(
                f"Completed Turn Action result is invalid: {message.call_id}"
            ) from exc
        if envelope.action_name != message.tool_name:
            raise SessionInvariantError(
                f"Completed Turn Action result name mismatch: {message.call_id}"
            )
        expected_status = {
            "success": ToolResultStatus.OK,
            "failed": ToolResultStatus.ERROR,
            "timeout": ToolResultStatus.ERROR,
        }[envelope.status.value]
        if message.status is not expected_status:
            raise SessionInvariantError(
                f"Completed Turn Action result status mismatch: {message.call_id}"
            )
        values.append(
            _ActionResult(
                call_id=message.call_id,
                action=message.tool_name,
                envelope=envelope,
                references=entry.origin_refs,
            )
        )
    return tuple(values)


_CallValue = TypeVar("_CallValue", _ActionCall, _ActionResult)


def _unique_by_id(
    values: tuple[_CallValue, ...],
    *,
    owner: str,
) -> dict[str, _CallValue]:
    result: dict[str, _CallValue] = {}
    for value in values:
        call_id = getattr(value, "call_id", None)
        if not isinstance(call_id, str) or not call_id:
            raise SessionInvariantError(f"Completed Turn Action {owner} id is invalid")
        if call_id in result:
            raise SessionInvariantError(
                f"Completed Turn contains duplicate Action {owner}: {call_id}"
            )
        result[call_id] = value
    return result
