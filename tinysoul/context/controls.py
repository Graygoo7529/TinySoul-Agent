"""Context control tools and control call normalization."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4

from tinysoul.infra.json import JsonObject, JsonValue
from tinysoul.llm.tools import ToolCallRecord, ToolKind, ToolScope, ToolSelection, ToolSpec
from tinysoul.runtime import RunScope, Signal

from .signals import (
    BackgroundPatch,
    build_background_patch_signal,
    build_working_patch_signal,
)
from .working import Milestone, TodoItem, TodoStatus, WorkingPatch

CONTROL_UPDATE_WORKING = "update_working"
CONTROL_LOAD_BACKGROUND = "load_background"
CONTROL_EVICT_BACKGROUND = "evict_background"

CONTROL_SIGNAL_SOURCE = "context.controls"


class ControlResultStatus(StrEnum):
    """Final status for one context control call."""

    SUCCESS = "success"
    FAILED = "failed"


class ControlResultStage(StrEnum):
    """The stage where a control result was produced."""

    NORMALIZE = "normalize"
    CONSUME = "consume"


@dataclass(frozen=True)
class ControlResult:
    """A structured local result for one model-side control call."""

    result_id: str
    call_id: str
    tool_name: str
    status: ControlResultStatus
    stage: ControlResultStage
    sequence: int
    model_feedback: str = ""
    frame_data: JsonObject = field(default_factory=dict)

    @classmethod
    def failed(
        cls,
        *,
        call_id: str,
        tool_name: str,
        stage: ControlResultStage,
        sequence: int,
        model_feedback: str,
        frame_data: JsonObject | None = None,
    ) -> "ControlResult":
        return cls(
            result_id=f"control_result_{uuid4().hex[:8]}",
            call_id=call_id,
            tool_name=tool_name,
            status=ControlResultStatus.FAILED,
            stage=stage,
            sequence=sequence,
            model_feedback=model_feedback,
            frame_data=frame_data or {},
        )


@dataclass(frozen=True)
class ControlNormalization:
    """Normalized context control calls: state signals plus local failures."""

    signals: tuple[Signal, ...] = field(default_factory=tuple)
    results: tuple[ControlResult, ...] = field(default_factory=tuple)


class ContextControlScopeBuilder:
    """Build the Phase1 context control tool scope."""

    def build(
        self,
        *,
        loadable_links: tuple[str, ...],
        loaded_links: tuple[str, ...],
    ) -> ToolScope:
        tools: list[ToolSpec] = [self._update_working_spec()]
        if loadable_links:
            tools.append(self._load_background_spec(loadable_links))
        if loaded_links:
            tools.append(self._evict_background_spec(loaded_links))
        return ToolScope(
            tools=tuple(tools),
            selection=ToolSelection(allowed_names=tuple(tool.name for tool in tools)),
        )

    def _update_working_spec(self) -> ToolSpec:
        item: JsonObject = {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Stable item key."},
                "content": {"type": "string", "description": "Item content."},
            },
            "required": ["key", "content"],
            "additionalProperties": False,
        }
        todo_item: JsonObject = {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Stable todo key."},
                "content": {"type": "string", "description": "Todo content."},
                "status": {
                    "type": "string",
                    "enum": [status.value for status in TodoStatus],
                    "description": "Todo status.",
                },
            },
            "required": ["key", "content"],
            "additionalProperties": False,
        }
        return ToolSpec(
            name=CONTROL_UPDATE_WORKING,
            description=(
                "Update the working context: set or remove milestones and todos. "
                "Provide at least one operation."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "set_milestones": {"type": "array", "items": item},
                    "remove_milestones": {"type": "array", "items": {"type": "string"}},
                    "set_todos": {"type": "array", "items": todo_item},
                    "remove_todos": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": False,
            },
            kind=ToolKind.CONTROL,
        )

    def _load_background_spec(self, loadable_links: tuple[str, ...]) -> ToolSpec:
        return ToolSpec(
            name=CONTROL_LOAD_BACKGROUND,
            description="Load top-level content entries into the background context.",
            parameters={
                "type": "object",
                "properties": {
                    "links": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(loadable_links)},
                        "description": "Top-level content links to load.",
                    },
                },
                "required": ["links"],
                "additionalProperties": False,
            },
            kind=ToolKind.CONTROL,
        )

    def _evict_background_spec(self, loaded_links: tuple[str, ...]) -> ToolSpec:
        return ToolSpec(
            name=CONTROL_EVICT_BACKGROUND,
            description="Evict loaded top-level content entries from the background context.",
            parameters={
                "type": "object",
                "properties": {
                    "links": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(loaded_links)},
                        "description": "Loaded top-level content links to evict.",
                    },
                },
                "required": ["links"],
                "additionalProperties": False,
            },
            kind=ToolKind.CONTROL,
        )


class ControlCallNormalizer:
    """Normalize Phase1 context control tool calls into state signals."""

    def normalize(
        self,
        tool_calls: tuple[ToolCallRecord, ...],
        *,
        scope: RunScope,
    ) -> ControlNormalization:
        signals: list[Signal] = []
        results: list[ControlResult] = []
        seen_call_ids: set[str] = set()
        for index, tool_call in enumerate(tool_calls):
            sequence = index + 1
            if tool_call.id in seen_call_ids:
                results.append(
                    _normalize_failure(
                        tool_call,
                        sequence=sequence,
                        model_feedback=f"Duplicate control tool call id: {tool_call.id}",
                        frame_data={"reason": "duplicate_call_id"},
                    )
                )
                continue
            seen_call_ids.add(tool_call.id)
            if tool_call.kind is not None and tool_call.kind is not ToolKind.CONTROL:
                results.append(
                    _normalize_failure(
                        tool_call,
                        sequence=sequence,
                        model_feedback="Expected a control tool call.",
                        frame_data={"tool_kind": tool_call.kind.value},
                    )
                )
                continue
            outcome = self._normalize_one(tool_call, scope=scope, sequence=sequence)
            if isinstance(outcome, ControlResult):
                results.append(outcome)
            else:
                signals.append(outcome)
        return ControlNormalization(signals=tuple(signals), results=tuple(results))

    def _normalize_one(
        self,
        tool_call: ToolCallRecord,
        *,
        scope: RunScope,
        sequence: int,
    ) -> Signal | ControlResult:
        if tool_call.name == CONTROL_UPDATE_WORKING:
            return self._normalize_update_working(tool_call, scope=scope, sequence=sequence)
        if tool_call.name in (CONTROL_LOAD_BACKGROUND, CONTROL_EVICT_BACKGROUND):
            return self._normalize_background(tool_call, scope=scope, sequence=sequence)
        return _normalize_failure(
            tool_call,
            sequence=sequence,
            model_feedback=f"Unknown context control tool: {tool_call.name}",
            frame_data={"reason": "unknown_control_tool"},
        )

    def _normalize_update_working(
        self,
        tool_call: ToolCallRecord,
        *,
        scope: RunScope,
        sequence: int,
    ) -> Signal | ControlResult:
        try:
            patch = WorkingPatch(
                set_milestones=tuple(
                    Milestone(key=_arg_str(item, "key"), content=_arg_str(item, "content"))
                    for item in _arg_object_list(tool_call.arguments, "set_milestones")
                ),
                remove_milestones=_arg_str_list(tool_call.arguments, "remove_milestones"),
                set_todos=tuple(
                    TodoItem(
                        key=_arg_str(item, "key"),
                        content=_arg_str(item, "content"),
                        status=_arg_todo_status(item),
                    )
                    for item in _arg_object_list(tool_call.arguments, "set_todos")
                ),
                remove_todos=_arg_str_list(tool_call.arguments, "remove_todos"),
            )
        except ControlArgumentError as exc:
            return _normalize_failure(
                tool_call,
                sequence=sequence,
                model_feedback=str(exc),
                frame_data={"reason": "invalid_arguments"},
            )
        if patch.is_empty():
            return _normalize_failure(
                tool_call,
                sequence=sequence,
                model_feedback="update_working requires at least one operation.",
                frame_data={"reason": "empty_patch"},
            )
        return build_working_patch_signal(
            patch,
            call_id=tool_call.id,
            scope=scope,
            source=CONTROL_SIGNAL_SOURCE,
        )

    def _normalize_background(
        self,
        tool_call: ToolCallRecord,
        *,
        scope: RunScope,
        sequence: int,
    ) -> Signal | ControlResult:
        try:
            links = _arg_str_list(tool_call.arguments, "links")
        except ControlArgumentError as exc:
            return _normalize_failure(
                tool_call,
                sequence=sequence,
                model_feedback=str(exc),
                frame_data={"reason": "invalid_arguments"},
            )
        if not links:
            return _normalize_failure(
                tool_call,
                sequence=sequence,
                model_feedback=f"{tool_call.name} requires at least one link.",
                frame_data={"reason": "empty_links"},
            )
        patch = (
            BackgroundPatch(load_links=links)
            if tool_call.name == CONTROL_LOAD_BACKGROUND
            else BackgroundPatch(evict_links=links)
        )
        return build_background_patch_signal(
            patch,
            call_id=tool_call.id,
            scope=scope,
            source=CONTROL_SIGNAL_SOURCE,
        )


class ControlArgumentError(ValueError):
    """Raised while parsing control tool call arguments."""


def _normalize_failure(
    tool_call: ToolCallRecord,
    *,
    sequence: int,
    model_feedback: str,
    frame_data: JsonObject | None = None,
) -> ControlResult:
    return ControlResult.failed(
        call_id=tool_call.id,
        tool_name=tool_call.name,
        stage=ControlResultStage.NORMALIZE,
        sequence=sequence,
        model_feedback=model_feedback,
        frame_data=frame_data,
    )


def _arg_str(value: JsonObject, name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item:
        raise ControlArgumentError(f"Argument must be a non-empty string: {name}")
    return item


def _arg_str_list(value: JsonObject, name: str) -> tuple[str, ...]:
    item: JsonValue = value.get(name)
    if item is None:
        return ()
    if not isinstance(item, list):
        raise ControlArgumentError(f"Argument must be a string list: {name}")
    result: list[str] = []
    for element in item:
        if not isinstance(element, str) or not element:
            raise ControlArgumentError(f"Argument must contain non-empty strings: {name}")
        result.append(element)
    return tuple(result)


def _arg_object_list(value: JsonObject, name: str) -> tuple[JsonObject, ...]:
    item: JsonValue = value.get(name)
    if item is None:
        return ()
    if not isinstance(item, list):
        raise ControlArgumentError(f"Argument must be an object list: {name}")
    result: list[JsonObject] = []
    for element in item:
        if not isinstance(element, dict):
            raise ControlArgumentError(f"Argument must contain objects: {name}")
        result.append(element)
    return tuple(result)


def _arg_todo_status(item: JsonObject) -> TodoStatus:
    raw = item.get("status", TodoStatus.PENDING.value)
    if not isinstance(raw, str):
        raise ControlArgumentError("Todo status must be a string")
    try:
        return TodoStatus(raw)
    except ValueError as exc:
        raise ControlArgumentError(f"Unknown todo status: {raw}") from exc
