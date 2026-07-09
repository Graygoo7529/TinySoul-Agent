from __future__ import annotations

import pytest

from tinysoul.llm.errors import LLMContractError
from tinysoul.llm.tools import (
    DefaultToolCallIdMapper,
    ToolCallRecord,
    ToolKind,
    ToolScope,
    ToolSelection,
    ToolSpec,
)


def test_tool_spec_requires_name_and_description() -> None:
    with pytest.raises(LLMContractError):
        ToolSpec(
            name="",
            description="desc",
            parameters={"type": "object"},
            kind=ToolKind.CONTROL,
        )

    with pytest.raises(LLMContractError):
        ToolSpec(
            name="update_context",
            description="",
            parameters={"type": "object"},
            kind=ToolKind.CONTROL,
        )


def test_tool_selection_validates_names() -> None:
    assert ToolSelection(("read_file",)).allowed_names == ("read_file",)
    assert ToolSelection(("read_file",), forced_name="read_file").forced_name == "read_file"

    with pytest.raises(LLMContractError):
        ToolSelection(("",))

    with pytest.raises(LLMContractError):
        ToolSelection(("read_file", "read_file"))

    with pytest.raises(LLMContractError):
        ToolSelection(("read_file",), forced_name="write_file")


def test_tool_scope_validates_selection_against_tools() -> None:
    tool = ToolSpec(
        name="read_file",
        description="Read",
        parameters={"type": "object"},
        kind=ToolKind.ACTION,
    )

    assert ToolScope(
        tools=(tool,),
        selection=ToolSelection(forced_name="read_file"),
    ).selection.forced_name == "read_file"

    with pytest.raises(LLMContractError):
        ToolScope(
            tools=(tool,),
            selection=ToolSelection(("write_file",)),
        )


def test_tool_scope_reports_visible_tools_and_empty_state() -> None:
    read_tool = ToolSpec(
        name="read_file",
        description="Read",
        parameters={"type": "object"},
        kind=ToolKind.ACTION,
    )
    write_tool = ToolSpec(
        name="write_file",
        description="Write",
        parameters={"type": "object"},
        kind=ToolKind.ACTION,
    )

    assert ToolScope().is_empty()
    scope = ToolScope(
        tools=(read_tool, write_tool),
        selection=ToolSelection(("read_file",)),
    )

    assert not scope.is_empty()
    assert scope.visible_tools() == (read_tool,)


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
    assert mapper.to_provider_id("read_file_2") == "read_file_2"
