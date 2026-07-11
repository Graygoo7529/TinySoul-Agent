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
from tinysoul.llm.tools import ToolCallRecord, ToolKind, ToolScope, ToolSelection, ToolSpec, ToolUse


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


def test_interpreter_extracts_json_after_scalar_with_brace_in_string() -> None:
    response = RawResponse(
        answer_text='1 ignored {"text": "keep } inside", "ok": true} done',
        model_id="model-a",
        provider_id="provider-a",
    )

    result = ResponseInterpreter().interpret(
        response,
        AnswerFormat.JSON_OBJECT,
        ToolUse.DISABLED,
    )

    assert result.answer == JsonAnswer({"text": "keep } inside", "ok": True})


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


def test_interpreter_accepts_forced_tool_among_other_tool_calls() -> None:
    read_call = ToolCallRecord(
        id="call_1",
        name="read_file",
        arguments={"path": "workspace:doc.md"},
    )
    write_call = ToolCallRecord(
        id="call_2",
        name="write_file",
        arguments={"path": "workspace:out.md"},
    )
    response = RawResponse(
        answer_text="",
        model_id="model-a",
        provider_id="provider-a",
        tool_calls=(write_call, read_call),
    )
    tool_scope = ToolScope(
        tools=(_tool("read_file"), _tool("write_file")),
        selection=ToolSelection(forced_name="read_file"),
    )

    result = ResponseInterpreter().interpret(
        response,
        AnswerFormat.NONE,
        ToolUse.REQUIRED,
        tool_scope=tool_scope,
    )

    assert result.tool_calls == (write_call, read_call)


def test_interpreter_rejects_missing_forced_tool_call() -> None:
    response = RawResponse(
        answer_text="",
        model_id="model-a",
        provider_id="provider-a",
        tool_calls=(
            ToolCallRecord(id="call_1", name="write_file", arguments={}),
        ),
    )
    tool_scope = ToolScope(
        tools=(_tool("read_file"), _tool("write_file")),
        selection=ToolSelection(forced_name="read_file"),
    )

    with pytest.raises(ResponseInterpretError):
        ResponseInterpreter().interpret(
            response,
            AnswerFormat.NONE,
            ToolUse.REQUIRED,
            tool_scope=tool_scope,
        )


def test_interpreter_rejects_unexpected_tool_call() -> None:
    response = RawResponse(
        answer_text="",
        model_id="model-a",
        provider_id="provider-a",
        tool_calls=(
            ToolCallRecord(id="call_1", name="write_file", arguments={}),
        ),
    )

    with pytest.raises(ResponseInterpretError):
        ResponseInterpreter().interpret(
            response,
            AnswerFormat.NONE,
            ToolUse.REQUIRED,
            tool_scope=ToolScope(tools=(_tool("read_file"),)),
        )


def _tool(name: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=f"{name} tool",
        parameters={"type": "object"},
        kind=ToolKind.ACTION,
    )
