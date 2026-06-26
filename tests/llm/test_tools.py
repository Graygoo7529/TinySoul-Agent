from __future__ import annotations

import pytest

from tinysoul.llm.tools import (
    DefaultToolCallIdMapper,
    ToolCallRecord,
    ToolKind,
    ToolSelection,
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


def test_tool_selection_validates_names() -> None:
    assert ToolSelection(("read_file",)).allowed_names == ("read_file",)

    with pytest.raises(ValueError):
        ToolSelection(("",))

    with pytest.raises(ValueError):
        ToolSelection(("read_file", "read_file"))


def test_tool_call_record_normalizes_arguments() -> None:
    call = ToolCallRecord(
        id="call_1",
        name="read_file",
        arguments={"path": "workspace:doc.md"},
        kind=ToolKind.ACTION,
    )

    assert call.arguments == {"path": "workspace:doc.md"}
    assert call.kind is ToolKind.ACTION


def test_default_tool_call_id_mapper_keeps_valid_provider_id() -> None:
    mapper = DefaultToolCallIdMapper()

    assert (
        mapper.to_tinysoul_id("call_1", index=0, tool_name="read_file")
        == "call_1"
    )
    assert mapper.to_provider_id("call_1") == "call_1"


def test_default_tool_call_id_mapper_generates_provider_friendly_id() -> None:
    mapper = DefaultToolCallIdMapper()

    assert (
        mapper.to_tinysoul_id("1 bad", index=1, tool_name="read/file")
        == "read_file_2"
    )
