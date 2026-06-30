"""Unified LLM response models and interpretation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import json
import re

from tinysoul.infra.json import JsonObject, to_json_object

from .reasoning import Reasoning
from .tools import ToolCallRecord, ToolScope, ToolUse


class AnswerFormat(StrEnum):
    """Expected model answer format."""

    NONE = "none"
    TEXT = "text"
    JSON_OBJECT = "json_object"


@dataclass(frozen=True)
class RawResponse:
    """Provider-normalized raw model response."""

    answer_text: str
    model_id: str
    provider_id: str
    tool_calls: tuple[ToolCallRecord, ...] = field(default_factory=tuple)
    reasoning: Reasoning | None = None
    usage: dict[str, object] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)
    provider_payload: JsonObject | None = None


@dataclass(frozen=True)
class TextAnswer:
    """Interpreted text answer."""

    text: str


@dataclass(frozen=True)
class JsonAnswer:
    """Interpreted JSON object answer."""

    value: JsonObject


Answer = TextAnswer | JsonAnswer


class TaskResultStatus(StrEnum):
    """Completion status of a task result."""

    SUCCESS = "success"
    FAILURE = "failure"


TASK_FAILURE_RESPONSE_INTERPRETATION_FAILED = "llm.response_interpretation_failed"


@dataclass(frozen=True)
class TaskFailure:
    """Feedback and frame data for a failed task result."""

    kind: str
    model_feedback: str | None = None
    frame_data: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.kind:
            raise ValueError("TaskFailure.kind must be non-empty")
        object.__setattr__(self, "frame_data", to_json_object(self.frame_data))


@dataclass(frozen=True)
class TaskResult:
    """Interpreted task result."""

    status: TaskResultStatus
    raw_response: RawResponse
    answer: Answer | None
    tool_calls: tuple[ToolCallRecord, ...] = field(default_factory=tuple)
    failure: TaskFailure | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, TaskResultStatus):
            raise TypeError("TaskResult.status must be a TaskResultStatus")
        if self.status is TaskResultStatus.SUCCESS and self.failure is not None:
            raise ValueError("Successful task results cannot carry failure data")
        if self.status is TaskResultStatus.FAILURE and self.failure is None:
            raise ValueError("Failed task results must carry failure data")
        object.__setattr__(self, "tool_calls", tuple(self.tool_calls))
        if self.failure is not None and not isinstance(self.failure, TaskFailure):
            raise TypeError("TaskResult.failure must be a TaskFailure or None")

    @classmethod
    def success(
        cls,
        *,
        raw_response: RawResponse,
        answer: Answer | None,
        tool_calls: tuple[ToolCallRecord, ...],
    ) -> "TaskResult":
        return cls(
            status=TaskResultStatus.SUCCESS,
            raw_response=raw_response,
            answer=answer,
            tool_calls=tool_calls,
        )

    @classmethod
    def failure_result(
        cls,
        *,
        raw_response: RawResponse,
        failure: TaskFailure,
        answer: Answer | None = None,
        tool_calls: tuple[ToolCallRecord, ...] = (),
    ) -> "TaskResult":
        return cls(
            status=TaskResultStatus.FAILURE,
            raw_response=raw_response,
            answer=answer,
            tool_calls=tool_calls,
            failure=failure,
        )


class ResponseInterpretError(Exception):
    """Raised when a model response cannot satisfy task settings."""


class ResponseInterpreter:
    """Interpret raw model responses according to task settings."""

    def interpret(
        self,
        response: RawResponse,
        answer_format: AnswerFormat,
        tool_use: ToolUse,
        *,
        tool_scope: ToolScope | None = None,
    ) -> TaskResult:
        answer: Answer | None
        if answer_format is AnswerFormat.NONE:
            answer = None
        elif answer_format is AnswerFormat.TEXT:
            answer = TextAnswer(response.answer_text)
        elif answer_format is AnswerFormat.JSON_OBJECT:
            answer = JsonAnswer(self._parse_json_object(response.answer_text))
        else:
            raise ResponseInterpretError(f"Unsupported answer format: {answer_format}")

        tool_calls = self._interpret_tool_calls(
            response,
            tool_use,
            tool_scope=tool_scope,
        )
        return TaskResult.success(
            raw_response=response,
            answer=answer,
            tool_calls=tool_calls,
        )

    def _interpret_tool_calls(
        self,
        response: RawResponse,
        tool_use: ToolUse,
        *,
        tool_scope: ToolScope | None,
    ) -> tuple[ToolCallRecord, ...]:
        if tool_use is ToolUse.DISABLED:
            if response.tool_calls:
                raise ResponseInterpretError("Tool calls are disabled for this task")
            return ()
        if tool_use is ToolUse.OPTIONAL:
            return self._validate_tool_scope(response.tool_calls, tool_scope)
        if tool_use is ToolUse.REQUIRED:
            if not response.tool_calls:
                raise ResponseInterpretError("Expected at least one tool call")
            return self._validate_tool_scope(response.tool_calls, tool_scope)
        raise ResponseInterpretError(f"Unsupported tool use: {tool_use}")

    def _validate_tool_scope(
        self,
        tool_calls: tuple[ToolCallRecord, ...],
        tool_scope: ToolScope | None,
    ) -> tuple[ToolCallRecord, ...]:
        if not tool_calls or tool_scope is None:
            return tool_calls
        visible_names = {tool.name for tool in tool_scope.visible_tools()}
        for tool_call in tool_calls:
            if tool_call.name not in visible_names:
                raise ResponseInterpretError(
                    f"Unexpected tool call: {tool_call.name}"
                )
        forced_name = tool_scope.selection.forced_name
        if forced_name is not None and not any(
            tool_call.name == forced_name for tool_call in tool_calls
        ):
            raise ResponseInterpretError(f"Expected forced tool call: {forced_name}")
        return tool_calls

    def _parse_json_object(self, text: str) -> JsonObject:
        cleaned = _extract_json_text(text)
        try:
            value = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ResponseInterpretError(
                f"Failed to parse model response as JSON object: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise ResponseInterpretError(
                f"Expected JSON object, got {type(value).__name__}"
            )
        return to_json_object(value)


def _extract_json_text(text: str) -> str:
    stripped = text.strip()
    fenced = re.search(r"```json\s*\n(.*?)\n\s*```", stripped, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()

    start = stripped.find("{")
    if start == -1:
        return stripped

    depth = 0
    for index, char in enumerate(stripped[start:], start):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return stripped[start : index + 1]
    return stripped[start:]
