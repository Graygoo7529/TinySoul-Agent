"""Unified LLM response models and interpretation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import json
import re

from tinysoul.infra.json import JsonObject, to_json_object

from .reasoning import Reasoning


class ResponseContract(StrEnum):
    """Expected model output shape."""

    TEXT = "text"
    JSON_OBJECT = "json_object"


@dataclass(frozen=True)
class ModelResponse:
    """Provider-normalized model response."""

    answer: str
    model_id: str
    provider_id: str
    reasoning: Reasoning | None = None
    usage: dict[str, object] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class TextTaskOutput:
    """Interpreted text task output."""

    text: str


@dataclass(frozen=True)
class JsonObjectTaskOutput:
    """Interpreted JSON object task output."""

    value: JsonObject


TaskOutput = TextTaskOutput | JsonObjectTaskOutput


@dataclass(frozen=True)
class TaskResult:
    """Interpreted task result."""

    response: ModelResponse
    output: TaskOutput


class ResponseInterpretError(Exception):
    """Raised when a model response cannot satisfy its response contract."""


class ResponseInterpreter:
    """Interpret model responses according to a response contract."""

    def interpret(
        self,
        response: ModelResponse,
        contract: ResponseContract,
    ) -> TaskResult:
        if contract is ResponseContract.TEXT:
            return TaskResult(
                response=response,
                output=TextTaskOutput(response.answer),
            )
        if contract is ResponseContract.JSON_OBJECT:
            return TaskResult(
                response=response,
                output=JsonObjectTaskOutput(self._parse_json_object(response.answer)),
            )
        raise ResponseInterpretError(f"Unsupported response contract: {contract}")

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
