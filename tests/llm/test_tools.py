from __future__ import annotations

import pytest

from tinysoul.llm.tools import (
    ToolCallRecord,
    ToolChoice,
    ToolChoiceMode,
    ToolKind,
    ToolSpec,
)


def test_tool_spec_requires_name_and_description() -> None:
    with pytest.raises(ValueError):
        ToolSpec(
            name="",
            description="desc",
            parameters={"type": "object"},
            kind=ToolKind.CONTROL,
        )

    with pytest.raises(ValueError):
        ToolSpec(
            name="update_context",
            description="",
            parameters={"type": "object"},
            kind=ToolKind.CONTROL,
        )


def test_tool_choice_validates_mode_constraints() -> None:
    assert ToolChoice.auto("read_file").mode is ToolChoiceMode.AUTO
    assert ToolChoice.required(forced_name="read_file").forced_name == "read_file"

    with pytest.raises(ValueError):
        ToolChoice.none().__class__(
            mode=ToolChoiceMode.NONE,
            allowed_names=("read_file",),
        )

    with pytest.raises(ValueError):
        ToolChoice(mode=ToolChoiceMode.AUTO, forced_name="read_file")


def test_tool_call_record_normalizes_arguments() -> None:
    call = ToolCallRecord(
        id="call_1",
        name="read_file",
        arguments={"path": "workspace:doc.md"},
        kind=ToolKind.ACTION,
    )

    assert call.arguments == {"path": "workspace:doc.md"}
    assert call.kind is ToolKind.ACTION
