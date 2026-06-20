from __future__ import annotations

import pytest

from tinysoul.llm.responses import (
    JsonObjectTaskOutput,
    ModelResponse,
    ResponseContract,
    ResponseInterpretError,
    ResponseInterpreter,
    TextTaskOutput,
)


def test_interpreter_extracts_json_object_from_fenced_text() -> None:
    response = ModelResponse(
        answer='```json\n{"ok": true, "count": 2}\n```',
        model_id="model-a",
        provider_id="provider-a",
    )

    result = ResponseInterpreter().interpret(response, ResponseContract.JSON_OBJECT)

    assert result.output == JsonObjectTaskOutput({"ok": True, "count": 2})


def test_interpreter_returns_text_output_for_text_contract() -> None:
    response = ModelResponse(
        answer="plain answer",
        model_id="model-a",
        provider_id="provider-a",
    )

    result = ResponseInterpreter().interpret(response, ResponseContract.TEXT)

    assert result.output == TextTaskOutput("plain answer")


def test_interpreter_rejects_json_array_for_json_object_contract() -> None:
    response = ModelResponse(
        answer="[1, 2]",
        model_id="model-a",
        provider_id="provider-a",
    )

    with pytest.raises(ResponseInterpretError):
        ResponseInterpreter().interpret(response, ResponseContract.JSON_OBJECT)
