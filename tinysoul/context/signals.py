"""Context signal protocol: names and payload codecs.

Producers (Phase1 normalization inside this module, and the loop module for
trace/input signals) build signals with the helpers below; ContextEngine parses
and consumes the feasible state changes in batches. Payloads stay JSON-safe.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from tinysoul.infra.json import JsonObject, JsonValue
from tinysoul.llm.messages import (
    AssistantMessage,
    JsonPart,
    TextPart,
    ToolResultMessage,
)
from tinysoul.llm.reasoning import Reasoning
from tinysoul.llm.tools import ToolCallRecord, ToolKind, ToolResultStatus
from tinysoul.runtime import CyclePhase, RunScope, Signal

from .errors import ContextContractError
from .background import BackgroundPatch
from .working import Milestone, TodoItem, TodoStatus, WorkingPatch, WorkspaceResource

SIGNAL_NAMESPACE = "context"
SIGNAL_WORKING_PATCH = "context.working.patch"
SIGNAL_BACKGROUND_PATCH = "context.background.patch"
SIGNAL_TRACE_APPEND = "context.trace.append"
SIGNAL_INPUT_APPEND = "context.input.append"


# ---------------------------------------------------------------------------
# Working patch


def build_working_patch_signal(
    patch: WorkingPatch,
    *,
    call_id: str,
    scope: RunScope,
    source: str,
) -> Signal:
    return Signal(
        name=SIGNAL_WORKING_PATCH,
        source=source,
        scope=scope,
        payload={"call_id": call_id, "patch": working_patch_to_json(patch)},
    )


def parse_working_patch_signal(signal: Signal) -> tuple[str, WorkingPatch]:
    call_id = _required_str(signal.payload, "call_id")
    patch_value = signal.payload.get("patch")
    if not isinstance(patch_value, dict):
        raise ContextContractError("Working patch signal payload must contain a patch object")
    return call_id, working_patch_from_json(patch_value)


def working_patch_to_json(patch: WorkingPatch) -> JsonObject:
    return {
        "set_milestones": [
            {"key": item.key, "content": item.content} for item in patch.set_milestones
        ],
        "remove_milestones": list(patch.remove_milestones),
        "set_todos": [
            {"key": item.key, "content": item.content, "status": item.status.value}
            for item in patch.set_todos
        ],
        "remove_todos": list(patch.remove_todos),
        "set_resources": [
            {"link": item.link, "summary": item.summary} for item in patch.set_resources
        ],
        "remove_resources": list(patch.remove_resources),
    }


def working_patch_from_json(value: JsonObject) -> WorkingPatch:
    return WorkingPatch(
        set_milestones=tuple(
            Milestone(
                key=_required_str(item, "key"),
                content=_required_str(item, "content"),
            )
            for item in _object_list(value, "set_milestones")
        ),
        remove_milestones=_str_tuple(value, "remove_milestones"),
        set_todos=tuple(
            TodoItem(
                key=_required_str(item, "key"),
                content=_required_str(item, "content"),
                status=_todo_status(item),
            )
            for item in _object_list(value, "set_todos")
        ),
        remove_todos=_str_tuple(value, "remove_todos"),
        set_resources=tuple(
            WorkspaceResource(
                link=_required_str(item, "link"),
                summary=_required_str(item, "summary"),
            )
            for item in _object_list(value, "set_resources")
        ),
        remove_resources=_str_tuple(value, "remove_resources"),
    )


# ---------------------------------------------------------------------------
# Background patch


def build_background_patch_signal(
    patch: BackgroundPatch,
    *,
    call_id: str,
    scope: RunScope,
    source: str,
) -> Signal:
    return Signal(
        name=SIGNAL_BACKGROUND_PATCH,
        source=source,
        scope=scope,
        payload={
            "call_id": call_id,
            "load_links": list(patch.load_links),
            "evict_links": list(patch.evict_links),
        },
    )


def parse_background_patch_signal(signal: Signal) -> tuple[str, BackgroundPatch]:
    call_id = _required_str(signal.payload, "call_id")
    patch = BackgroundPatch(
        load_links=_str_tuple(signal.payload, "load_links"),
        evict_links=_str_tuple(signal.payload, "evict_links"),
    )
    if patch.is_empty():
        raise ContextContractError("Background patch signal contains no links")
    return call_id, patch


# ---------------------------------------------------------------------------
# Trace append


@dataclass(frozen=True)
class TraceAppend:
    """A parsed trace append request."""

    kind: "TraceAppendKind"
    cycle_id: str = ""
    phase: CyclePhase | None = None
    decision: AssistantMessage | None = None
    action_result: ToolResultMessage | None = None
    note: JsonObject | None = None


class TraceAppendKind(StrEnum):
    """Stable trace append signal kinds."""

    DECISION = "decision"
    ACTION_RESULT = "action_result"
    PHASE_NOTE = "phase_note"


TRACE_APPEND_DECISION = TraceAppendKind.DECISION.value
TRACE_APPEND_ACTION_RESULT = TraceAppendKind.ACTION_RESULT.value
TRACE_APPEND_PHASE_NOTE = TraceAppendKind.PHASE_NOTE.value


def build_trace_decision_signal(
    message: AssistantMessage,
    *,
    scope: RunScope,
    source: str,
    cycle_id: str = "",
    phase: CyclePhase | None = None,
) -> Signal:
    payload: JsonObject = {
        "kind": TRACE_APPEND_DECISION,
        "cycle_id": cycle_id,
        "phase": phase.value if phase is not None else "",
        "content": _parts_to_json(message.parts),
        "tool_calls": [
            {
                "id": record.id,
                "name": record.name,
                "arguments": record.arguments,
                "tool_kind": record.kind.value if record.kind is not None else "",
            }
            for record in message.tool_calls
        ],
    }
    reasoning = _reasoning_to_json(message.reasoning)
    if reasoning is not None:
        payload["reasoning"] = reasoning
    return Signal(name=SIGNAL_TRACE_APPEND, source=source, scope=scope, payload=payload)


def build_trace_action_result_signal(
    message: ToolResultMessage,
    *,
    scope: RunScope,
    source: str,
    cycle_id: str = "",
) -> Signal:
    payload: JsonObject = {
        "kind": TRACE_APPEND_ACTION_RESULT,
        "cycle_id": cycle_id,
        "call_id": message.call_id,
        "tool_name": message.tool_name,
        "status": message.status.value,
        "content": _parts_to_json(message.parts),
    }
    return Signal(name=SIGNAL_TRACE_APPEND, source=source, scope=scope, payload=payload)


def build_trace_phase_note_signal(
    note: JsonObject,
    *,
    scope: RunScope,
    source: str,
    cycle_id: str = "",
    phase: CyclePhase | None = None,
) -> Signal:
    payload: JsonObject = {
        "kind": TRACE_APPEND_PHASE_NOTE,
        "cycle_id": cycle_id,
        "phase": phase.value if phase is not None else "",
        "note": note,
    }
    return Signal(name=SIGNAL_TRACE_APPEND, source=source, scope=scope, payload=payload)


def parse_trace_append_signal(signal: Signal) -> TraceAppend:
    kind_value = _required_str(signal.payload, "kind")
    try:
        kind = TraceAppendKind(kind_value)
    except ValueError as exc:
        raise ContextContractError(f"Unknown trace append kind: {kind_value}") from exc
    cycle_id = _optional_str(signal.payload, "cycle_id")
    phase = _optional_phase(signal.payload)
    if kind is TraceAppendKind.DECISION:
        parts = _parts_from_json(signal.payload)
        if not parts:
            text = _optional_str(signal.payload, "text")
            if text:
                parts = (TextPart(text),)
        tool_calls = tuple(
            ToolCallRecord(
                id=_required_str(item, "id"),
                name=_required_str(item, "name"),
                arguments=_object_field(item, "arguments"),
                kind=_optional_tool_kind(item),
            )
            for item in _object_list(signal.payload, "tool_calls")
        )
        reasoning = _optional_reasoning(signal.payload)
        if not parts and not tool_calls and reasoning is None:
            raise ContextContractError("Trace decision signal has neither text nor tool calls")
        message = AssistantMessage.from_parts(
            *parts,
            reasoning=reasoning,
            tool_calls=tool_calls,
            label="decision",
        )
        return TraceAppend(
            kind=kind,
            cycle_id=cycle_id,
            phase=phase,
            decision=message,
        )
    if kind is TraceAppendKind.ACTION_RESULT:
        status_value = _required_str(signal.payload, "status")
        try:
            status = ToolResultStatus(status_value)
        except ValueError as exc:
            raise ContextContractError(
                f"Unknown tool result status: {status_value}"
            ) from exc
        parts = _parts_from_json(signal.payload)
        if parts:
            message = ToolResultMessage.from_parts(
                call_id=_required_str(signal.payload, "call_id"),
                tool_name=_required_str(signal.payload, "tool_name"),
                parts=parts,
                status=status,
                label="action_result",
            )
        else:
            value = signal.payload.get("value")
            text = _optional_str(signal.payload, "text")
            if isinstance(value, dict):
                message = ToolResultMessage.from_json(
                    call_id=_required_str(signal.payload, "call_id"),
                    tool_name=_required_str(signal.payload, "tool_name"),
                    value=value,
                    status=status,
                    label="action_result",
                )
            else:
                message = ToolResultMessage.from_text(
                    call_id=_required_str(signal.payload, "call_id"),
                    tool_name=_required_str(signal.payload, "tool_name"),
                    text=text or "(empty result)",
                    status=status,
                    label="action_result",
                )
        return TraceAppend(
            kind=kind,
            cycle_id=cycle_id,
            phase=CyclePhase.PHASE3,
            action_result=message,
        )
    if kind is TraceAppendKind.PHASE_NOTE:
        note = signal.payload.get("note")
        if not isinstance(note, dict) or not note:
            raise ContextContractError("Trace phase note signal requires a non-empty note object")
        return TraceAppend(kind=kind, cycle_id=cycle_id, phase=phase, note=note)
    raise ContextContractError(f"Unknown trace append kind: {kind.value}")


# ---------------------------------------------------------------------------
# Input append


def build_input_append_signal(
    text: str,
    *,
    scope: RunScope,
    source: str,
) -> Signal:
    if not text:
        raise ContextContractError("Input append signal requires non-empty text")
    return Signal(
        name=SIGNAL_INPUT_APPEND,
        source=source,
        scope=scope,
        payload={"text": text},
    )


def parse_input_append_signal(signal: Signal) -> str:
    return _required_str(signal.payload, "text")


# ---------------------------------------------------------------------------
# Payload parsing helpers


def _parts_to_json(parts: tuple[object, ...]) -> list[JsonValue]:
    result: list[JsonValue] = []
    for part in parts:
        if isinstance(part, TextPart):
            result.append({"type": "text", "text": part.text})
        elif isinstance(part, JsonPart):
            result.append({"type": "json", "value": part.value})
        else:
            raise ContextContractError(
                "Trace append only supports text and JSON message parts"
            )
    return result


def _parts_from_json(value: JsonObject) -> tuple[TextPart | JsonPart, ...]:
    result: list[TextPart | JsonPart] = []
    for item in _object_list(value, "content"):
        part_type = _required_str(item, "type")
        if part_type == "text":
            result.append(TextPart(_required_str(item, "text")))
        elif part_type == "json":
            result.append(JsonPart(_object_field(item, "value")))
        else:
            raise ContextContractError(f"Unknown trace content part type: {part_type}")
    return tuple(result)


def _reasoning_to_json(reasoning: Reasoning | None) -> JsonObject | None:
    if reasoning is None:
        return None
    result: JsonObject = {}
    if reasoning.content is not None:
        result["content"] = reasoning.content
    if reasoning.summary is not None:
        result["summary"] = reasoning.summary
    if reasoning.encrypted_items:
        result["encrypted_items"] = list(reasoning.encrypted_items)
    if not result:
        return None
    return result


def _optional_reasoning(value: JsonObject) -> Reasoning | None:
    raw = value.get("reasoning")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ContextContractError("Trace reasoning must be an object")
    content = _optional_nullable_str(raw, "content")
    summary = _optional_nullable_str(raw, "summary")
    encrypted_items = _object_list(raw, "encrypted_items")
    if content is None and summary is None and not encrypted_items:
        return None
    return Reasoning(
        content=content,
        summary=summary,
        encrypted_items=encrypted_items,
    )


def _required_str(value: JsonObject, name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item:
        raise ContextContractError(f"Signal payload field must be a non-empty string: {name}")
    return item


def _optional_str(value: JsonObject, name: str) -> str:
    item = value.get(name, "")
    if not isinstance(item, str):
        raise ContextContractError(f"Signal payload field must be a string: {name}")
    return item


def _optional_nullable_str(value: JsonObject, name: str) -> str | None:
    item = value.get(name)
    if item is None:
        return None
    if not isinstance(item, str):
        raise ContextContractError(f"Signal payload field must be a string: {name}")
    return item


def _str_tuple(value: JsonObject, name: str) -> tuple[str, ...]:
    item = value.get(name)
    if item is None:
        return ()
    if not isinstance(item, list):
        raise ContextContractError(f"Signal payload field must be a string list: {name}")
    result: list[str] = []
    for element in item:
        if not isinstance(element, str) or not element:
            raise ContextContractError(
                f"Signal payload field must contain non-empty strings: {name}"
            )
        result.append(element)
    return tuple(result)


def _object_list(value: JsonObject, name: str) -> tuple[JsonObject, ...]:
    item = value.get(name)
    if item is None:
        return ()
    if not isinstance(item, list):
        raise ContextContractError(f"Signal payload field must be an object list: {name}")
    result: list[JsonObject] = []
    for element in item:
        if not isinstance(element, dict):
            raise ContextContractError(
                f"Signal payload field must contain objects: {name}"
            )
        result.append(element)
    return tuple(result)


def _object_field(value: JsonObject, name: str) -> JsonObject:
    item = value.get(name)
    if not isinstance(item, dict):
        raise ContextContractError(f"Signal payload field must be an object: {name}")
    return item


def _todo_status(item: JsonObject) -> TodoStatus:
    raw = item.get("status", TodoStatus.PENDING.value)
    if not isinstance(raw, str):
        raise ContextContractError("Todo status must be a string")
    try:
        return TodoStatus(raw)
    except ValueError as exc:
        raise ContextContractError(f"Unknown todo status: {raw}") from exc


def _optional_phase(value: JsonObject) -> CyclePhase | None:
    raw = value.get("phase", "")
    if not isinstance(raw, str):
        raise ContextContractError("Signal payload phase must be a string")
    if not raw:
        return None
    try:
        return CyclePhase(raw)
    except ValueError as exc:
        raise ContextContractError(f"Unknown cycle phase: {raw}") from exc


def _optional_tool_kind(item: JsonObject) -> ToolKind | None:
    raw = item.get("tool_kind", "")
    if not isinstance(raw, str):
        raise ContextContractError("Tool call kind must be a string")
    if not raw:
        return None
    try:
        return ToolKind(raw)
    except ValueError as exc:
        raise ContextContractError(f"Unknown tool kind: {raw}") from exc
