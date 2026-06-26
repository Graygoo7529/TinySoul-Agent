"""Unified LLM response models and interpretation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import json
import re

from tinysoul.infra.json import JsonObject, to_json_object

from .reasoning import Reasoning
from .tools import ToolCallRecord, ToolUse


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


@dataclass(frozen=True)
class TaskResult:
    """Interpreted task result."""

    raw_response: RawResponse
    answer: Answer | None
    tool_calls: tuple[ToolCallRecord, ...] = field(default_factory=tuple)


class ResponseInterpretError(Exception):
    """Raised when a model response cannot satisfy its response contract."""


class ResponseInterpreter:
    """Interpret raw model responses according to task settings."""

    def interpret(
        self,
        response: RawResponse,
        answer_format: AnswerFormat,
        tool_use: ToolUse,
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

        tool_calls = self._interpret_tool_calls(response, tool_use)
        return TaskResult(
            raw_response=response,
            answer=answer,
            tool_calls=tool_calls,
        )

    def _interpret_tool_calls(
        self,
        response: RawResponse,
        tool_use: ToolUse,
    ) -> tuple[ToolCallRecord, ...]:
        if tool_use is ToolUse.DISABLED:
            if response.tool_calls:
                raise ResponseInterpretError("Tool calls are disabled for this task")
            return ()
        if tool_use is ToolUse.OPTIONAL:
            return response.tool_calls
        if tool_use is ToolUse.REQUIRED:
            if not response.tool_calls:
                raise ResponseInterpretError("Expected at least one tool call")
            return response.tool_calls
        raise ResponseInterpretError(f"Unsupported tool use: {tool_use}")

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
