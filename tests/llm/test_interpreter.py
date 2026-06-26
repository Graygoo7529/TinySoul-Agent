from __future__ import annotations

import pytest

from tinysoul.llm.responses import (
    JsonAnswer,
    RawResponse,
    AnswerFormat,
    ResponseInterpretError,
    ResponseInterpreter,
    TextAnswer,
)
from tinysoul.llm.tools import ToolCallRecord, ToolUse


def test_interpreter_extracts_json_object_from_fenced_text() -> None:
    response = RawResponse(
        answer_text='```json\n{"ok": true, "count": 2}\n```',
        model_id="model-a",
        provider_id="provider-a",
    )

    result = ResponseInterpreter().interpret(
        response,
        AnswerFormat.JSON_OBJECT,
        ToolUse.DISABLED,
    )

    assert result.answer == JsonAnswer({"ok": True, "count": 2})


def test_interpreter_returns_text_output_for_text_contract() -> None:
    response = RawResponse(
        answer_text="plain answer",
        model_id="model-a",
        provider_id="provider-a",
    )

    result = ResponseInterpreter().interpret(
        response,
        AnswerFormat.TEXT,
        ToolUse.DISABLED,
    )

    assert result.answer == TextAnswer("plain answer")


def test_interpreter_rejects_json_array_for_json_object_contract() -> None:
    response = RawResponse(
        answer_text="[1, 2]",
        model_id="model-a",
        provider_id="provider-a",
    )

    with pytest.raises(ResponseInterpretError):
        ResponseInterpreter().interpret(
            response,
            AnswerFormat.JSON_OBJECT,
            ToolUse.DISABLED,
        )


def test_interpreter_allows_answer_and_tool_calls_together() -> None:
    tool_call = ToolCallRecord(
        id="call_1",
        name="read_file",
        arguments={"path": "workspace:doc.md"},
    )
    response = RawResponse(
        answer_text="I will read the file.",
        model_id="model-a",
        provider_id="provider-a",
        tool_calls=(tool_call,),
    )

    result = ResponseInterpreter().interpret(
        response,
        AnswerFormat.TEXT,
        ToolUse.OPTIONAL,
    )

    assert result.answer == TextAnswer("I will read the file.")
    assert result.tool_calls == (tool_call,)


def test_interpreter_rejects_tool_calls_when_disabled() -> None:
    response = RawResponse(
        answer_text="",
        model_id="model-a",
        provider_id="provider-a",
        tool_calls=(
            ToolCallRecord(id="call_1", name="read_file", arguments={}),
        ),
    )

    with pytest.raises(ResponseInterpretError):
        ResponseInterpreter().interpret(
            response,
            AnswerFormat.NONE,
            ToolUse.DISABLED,
        )


def test_interpreter_requires_tool_calls_when_required() -> None:
    response = RawResponse(
        answer_text="",
        model_id="model-a",
        provider_id="provider-a",
    )

    with pytest.raises(ResponseInterpretError):
        ResponseInterpreter().interpret(
            response,
            AnswerFormat.NONE,
            ToolUse.REQUIRED,
        )
