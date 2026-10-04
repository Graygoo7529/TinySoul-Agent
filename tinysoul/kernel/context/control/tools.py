"""Context control tools and control call normalization."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4

from tinysoul.prompts.kernel import context as prompt_text
from tinysoul.infra.json import JsonObject, JsonValue, to_json_object
from tinysoul.llm.protocol.tools import (
    ToolCallRecord,
    ToolKind,
    ToolScope,
    ToolSelection,
    ToolSpec,
)
from tinysoul.runtime import RunScope, Signal

from ..background import BackgroundPatch
from ..errors import ContextInvariantError
from ..signals import (
    SIGNAL_WORKING_PATCH,
    build_background_patch_signal,
    build_working_patch_signal,
    parse_background_patch_signal,
    parse_working_patch_signal,
)
from ..builtin.working import Milestone, TodoItem, TodoStatus, WorkingPatch

CONTROL_SET_MILESTONE = "set_milestone"
CONTROL_REMOVE_MILESTONE = "remove_milestone"
CONTROL_SET_TODO = "set_todo"
CONTROL_REMOVE_TODO = "remove_todo"
CONTROL_LOAD_BACKGROUND = "load_background"
CONTROL_EVICT_BACKGROUND = "evict_background"

CONTROL_SIGNAL_SOURCE = "context.controls"


def applied_control_payload(signal: Signal) -> JsonObject:
    """Describe one normalized, installed control without retaining model input."""
    if signal.name == SIGNAL_WORKING_PATCH:
        call_id, patch = parse_working_patch_signal(signal)
        if patch.set_todos:
            todo = patch.set_todos[0]
            operation = CONTROL_SET_TODO
            details: JsonObject = {
                "key": todo.key, "content": todo.content, "status": todo.status.value,
            }
        elif patch.remove_todos:
            operation = CONTROL_REMOVE_TODO
            details = {"key": patch.remove_todos[0]}
        elif patch.set_milestones:
            milestone = patch.set_milestones[0]
            operation = CONTROL_SET_MILESTONE
            details = {"key": milestone.key, "content": milestone.content}
        else:
            operation = CONTROL_REMOVE_MILESTONE
            details = {"key": patch.remove_milestones[0]}
    else:
        call_id, background = parse_background_patch_signal(signal)
        operation = CONTROL_LOAD_BACKGROUND if background.load_links else CONTROL_EVICT_BACKGROUND
        details = {"links": list(background.load_links or background.evict_links)}
    return to_json_object({"call_id": call_id, "operation": operation, "details": details})


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

    def __post_init__(self) -> None:
        if not self.result_id:
            raise ContextInvariantError("ControlResult.result_id must be non-empty")
        if not self.call_id:
            raise ContextInvariantError("ControlResult.call_id must be non-empty")
        if not self.tool_name:
            raise ContextInvariantError("ControlResult.tool_name must be non-empty")
        if not isinstance(self.status, ControlResultStatus):
            raise ContextInvariantError(
                "ControlResult.status must be a ControlResultStatus"
            )
        if not isinstance(self.stage, ControlResultStage):
            raise ContextInvariantError(
                "ControlResult.stage must be a ControlResultStage"
            )
        if self.sequence <= 0:
            raise ContextInvariantError("ControlResult.sequence must be positive")
        object.__setattr__(self, "frame_data", to_json_object(self.frame_data))

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

    def __post_init__(self) -> None:
        signals = tuple(self.signals)
        results = tuple(self.results)
        if any(not isinstance(signal, Signal) for signal in signals):
            raise ContextInvariantError(
                "ControlNormalization.signals must contain Signal values"
            )
        if any(not isinstance(result, ControlResult) for result in results):
            raise ContextInvariantError(
                "ControlNormalization.results must contain ControlResult values"
            )
        object.__setattr__(self, "signals", signals)
        object.__setattr__(self, "results", results)


class ContextControlScopeBuilder:
    """Build the Phase1 context control tool scope."""

    def build(
        self,
        *,
        loadable_links: tuple[str, ...],
        loaded_links: tuple[str, ...],
    ) -> ToolScope:
        tools: list[ToolSpec] = [
            self._set_milestone_spec(),
            self._remove_milestone_spec(),
            self._set_todo_spec(),
            self._remove_todo_spec(),
        ]
        if loadable_links:
            tools.append(self._load_background_spec())
        if loaded_links:
            tools.append(self._evict_background_spec(loaded_links))
        return ToolScope(
            tools=tuple(tools),
            selection=ToolSelection(allowed_names=tuple(tool.name for tool in tools)),
        )

    def _set_milestone_spec(self) -> ToolSpec:
        return ToolSpec(
            name=CONTROL_SET_MILESTONE,
            description=prompt_text.SET_MILESTONE_DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": prompt_text.STABLE_MILESTONE_KEY,
                    },
                    "content": {
                        "type": "string",
                        "description": prompt_text.MILESTONE_CONTENT,
                    },
                },
                "required": ["key", "content"],
                "additionalProperties": False,
            },
            kind=ToolKind.CONTROL,
        )

    def _remove_milestone_spec(self) -> ToolSpec:
        return _remove_working_spec(
            CONTROL_REMOVE_MILESTONE,
            description=prompt_text.REMOVE_MILESTONE_DESCRIPTION,
        )

    def _set_todo_spec(self) -> ToolSpec:
        return ToolSpec(
            name=CONTROL_SET_TODO,
            description=prompt_text.SET_TODO_DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": prompt_text.STABLE_TODO_KEY,
                    },
                    "content": {
                        "type": "string",
                        "description": prompt_text.TODO_CONTENT,
                    },
                    "status": {
                        "type": "string",
                        "enum": [status.value for status in TodoStatus],
                        "description": prompt_text.TODO_STATUS,
                    },
                },
                "required": ["key", "content", "status"],
                "additionalProperties": False,
            },
            kind=ToolKind.CONTROL,
        )

    def _remove_todo_spec(self) -> ToolSpec:
        return _remove_working_spec(
            CONTROL_REMOVE_TODO,
            description=prompt_text.REMOVE_TODO_DESCRIPTION,
        )

    def _load_background_spec(self) -> ToolSpec:
        return ToolSpec(
            name=CONTROL_LOAD_BACKGROUND,
            description=prompt_text.LOAD_BACKGROUND_DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "links": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "description": prompt_text.BACKGROUND_LINK_DESCRIPTION,
                        },
                        "description": prompt_text.TOP_LEVEL_CONTENT_LINKS_TO_LOAD_TOGETHER,
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
            description=prompt_text.EVICT_BACKGROUND_DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "links": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(loaded_links)},
                        "description": prompt_text.LOADED_TOP_LEVEL_CONTENT_LINKS_TO_EVICT,
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
                        model_feedback=prompt_text.duplicate_control_call(
                            call_id=tool_call.id
                        ),
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
                        model_feedback=prompt_text.EXPECTED_A_CONTROL_TOOL_CALL,
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
        if tool_call.name in {
            CONTROL_SET_MILESTONE,
            CONTROL_REMOVE_MILESTONE,
            CONTROL_SET_TODO,
            CONTROL_REMOVE_TODO,
        }:
            return self._normalize_working_operation(
                tool_call,
                scope=scope,
                sequence=sequence,
            )
        if tool_call.name in (CONTROL_LOAD_BACKGROUND, CONTROL_EVICT_BACKGROUND):
            return self._normalize_background(tool_call, scope=scope, sequence=sequence)
        return _normalize_failure(
            tool_call,
            sequence=sequence,
            model_feedback=prompt_text.unknown_control_tool(name=tool_call.name),
            frame_data={"reason": "unknown_control_tool"},
        )

    def _normalize_working_operation(
        self,
        tool_call: ToolCallRecord,
        *,
        scope: RunScope,
        sequence: int,
    ) -> Signal | ControlResult:
        try:
            patch = _working_operation_patch(tool_call)
        except ControlArgumentError as exc:
            return _normalize_failure(
                tool_call,
                sequence=sequence,
                model_feedback=str(exc),
                frame_data={"reason": "invalid_arguments"},
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
                model_feedback=prompt_text.links_required(name=tool_call.name),
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


class ControlArgumentError(Exception):
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
        raise ControlArgumentError(prompt_text.nonempty_string_required(name=name))
    return item


def _arg_str_list(value: JsonObject, name: str) -> tuple[str, ...]:
    item: JsonValue = value.get(name)
    if item is None:
        return ()
    if not isinstance(item, list):
        raise ControlArgumentError(prompt_text.string_list_required(name=name))
    result: list[str] = []
    for element in item:
        if not isinstance(element, str) or not element:
            raise ControlArgumentError(prompt_text.nonempty_strings_required(name=name))
        result.append(element)
    return tuple(result)


def _arg_todo_status(item: JsonObject) -> TodoStatus:
    raw = item.get("status")
    if not isinstance(raw, str):
        raise ControlArgumentError(prompt_text.TODO_STATUS_MUST_BE_A_STRING)
    try:
        return TodoStatus(raw)
    except ValueError as exc:
        raise ControlArgumentError(prompt_text.unknown_todo_status(raw=raw)) from exc


def _remove_working_spec(name: str, *, description: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        parameters={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": prompt_text.EXISTING_ITEM_KEY},
            },
            "required": ["key"],
            "additionalProperties": False,
        },
        kind=ToolKind.CONTROL,
    )


def _working_operation_patch(tool_call: ToolCallRecord) -> WorkingPatch:
    arguments = tool_call.arguments
    expected = (
        {"key", "content", "status"}
        if tool_call.name == CONTROL_SET_TODO
        else {"key", "content"} if tool_call.name == CONTROL_SET_MILESTONE else {"key"}
    )
    if set(arguments) != expected:
        raise ControlArgumentError(
            prompt_text.unexpected_control_arguments(
                name=tool_call.name, expected_arguments=", ".join(sorted(expected))
            )
        )
    key = _arg_str(arguments, "key")
    if tool_call.name == CONTROL_SET_MILESTONE:
        return WorkingPatch(
            set_milestones=(Milestone(key=key, content=_arg_str(arguments, "content")),)
        )
    if tool_call.name == CONTROL_REMOVE_MILESTONE:
        return WorkingPatch(remove_milestones=(key,))
    if tool_call.name == CONTROL_SET_TODO:
        return WorkingPatch(
            set_todos=(
                TodoItem(
                    key=key,
                    content=_arg_str(arguments, "content"),
                    status=_arg_todo_status(arguments),
                ),
            )
        )
    return WorkingPatch(remove_todos=(key,))
