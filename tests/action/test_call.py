from __future__ import annotations

from pathlib import Path

import pytest

from tinysoul.action.core.call import ActionCallNormalizer, ActionExecutionBuilder
from tinysoul.action.core.loader import ActionCatalogLoader
from tinysoul.llm.tools import ToolCallRecord, ToolKind
from tinysoul.runtime import RunScope


def test_normalize_tool_calls_to_action_calls() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/builtin"))
    tool_calls = (
        ToolCallRecord(
            id="call_1",
            name="core.answer",
            arguments={"text": "done"},
            kind=ToolKind.ACTION,
        ),
    )

    calls = ActionCallNormalizer().normalize(tool_calls, catalog=catalog)

    assert len(calls) == 1
    assert calls[0].action_name == "core.answer"
    assert calls[0].tool_call_id == "call_1"
    assert calls[0].params == {"text": "done"}


def test_normalizer_rejects_non_action_tool_call() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/builtin"))

    with pytest.raises(ValueError, match="Expected ACTION tool call"):
        ActionCallNormalizer().normalize(
            (
                ToolCallRecord(
                    id="call_1",
                    name="core.answer",
                    arguments={"text": "done"},
                    kind=ToolKind.CONTROL,
                ),
            ),
            catalog=catalog,
        )


def test_normalizer_rejects_invalid_action_arguments() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/builtin"))

    with pytest.raises(ValueError, match="Missing required action parameter"):
        ActionCallNormalizer().normalize(
            (
                ToolCallRecord(
                    id="call_1",
                    name="core.answer",
                    arguments={},
                    kind=ToolKind.ACTION,
                ),
            ),
            catalog=catalog,
        )


def test_normalizer_rejects_unexpected_action_arguments() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/builtin"))

    with pytest.raises(ValueError, match="Unexpected action parameter"):
        ActionCallNormalizer().normalize(
            (
                ToolCallRecord(
                    id="call_1",
                    name="workspace.scan",
                    arguments={"path": "."},
                    kind=ToolKind.ACTION,
                ),
            ),
            catalog=catalog,
        )


def test_build_execution_batch_from_calls() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/builtin"))
    calls = ActionCallNormalizer().normalize(
        (
            ToolCallRecord(
                id="call_1",
                name="workspace.scan",
                arguments={},
                kind=ToolKind.ACTION,
            ),
        ),
        catalog=catalog,
    )

    batch = ActionExecutionBuilder().build_batch(
        calls,
        catalog=catalog,
        scope=RunScope(),
        batch_id="batch_1",
    )

    assert batch.batch_id == "batch_1"
    assert batch.executions[0].framework.domain == "workspace"
    assert batch.executions[0].framework.timeout_seconds == 30.0
