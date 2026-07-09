from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

from tinysoul.action.core.errors import ActionContractError
from tinysoul.action.core.loader import ActionCatalogLoader
from tinysoul.action.core.scope import (
    ActionDomainPromptRenderer,
    Phase1DomainScopeBuilder,
    Phase2ActionScopeBuilder,
)
from tinysoul.infra.json import JsonValue
from tinysoul.llm.tools import ToolCallRecord, ToolKind


def test_phase1_scope_exposes_domain_control_tool() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/catalog"))

    scope = Phase1DomainScopeBuilder().build(catalog)

    tools = scope.visible_tools()
    assert len(tools) == 1
    assert tools[0].kind is ToolKind.CONTROL
    assert tools[0].name == "select_action_domains"
    properties = cast(Mapping[str, JsonValue], tools[0].parameters["properties"])
    domains = cast(Mapping[str, JsonValue], properties["domains"])
    items = cast(Mapping[str, JsonValue], domains["items"])
    enum = cast(list[JsonValue], items["enum"])
    assert "home" in enum
    assert "workspace" in enum
    assert "script" not in enum
    assert "shell" not in enum
    assert "x-tinysoul-domains" not in tools[0].parameters


def test_phase1_domain_selection_normalizer_belongs_to_action() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/catalog"))

    selection = Phase1DomainScopeBuilder().normalize_selection(
        catalog,
        (
            ToolCallRecord(
                id="call_1",
                name="select_action_domains",
                arguments={"domains": ["workspace", "missing", "workspace"]},
                kind=ToolKind.CONTROL,
            ),
        ),
    )

    assert selection.selected_domains == ("workspace",)
    assert selection.feedback == ("Unknown action domain: missing",)


def test_phase2_scope_exposes_selected_domain_actions_only() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/catalog"))

    scope = Phase2ActionScopeBuilder().build(
        catalog,
        selected_domains=("core",),
    )

    tools = scope.visible_tools()
    assert [tool.name for tool in tools] == ["core.answer", "core.reason"]
    assert tools[0].kind is ToolKind.ACTION
    assert "Use when:" in tools[0].description


def test_phase2_scope_rejects_domain_without_actions() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/catalog"))

    with pytest.raises(ActionContractError, match="at least one action"):
        Phase2ActionScopeBuilder().build(
            catalog,
            selected_domains=("script",),
        )


def test_phase2_scope_prepare_returns_phase_result_for_domain_without_actions() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/catalog"))

    preparation = Phase2ActionScopeBuilder().prepare(
        catalog,
        selected_domains=("script",),
    )

    assert preparation.tool_scope is None
    assert preparation.phase_results[0].stage.value == "scope"
    assert preparation.phase_results[0].frame_data["selected_domains"] == ["script"]


def test_domain_prompt_renderer_lists_actionable_domains() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/catalog"))

    text = ActionDomainPromptRenderer().render(catalog)

    assert "workspace:" in text
    assert "home:" in text
    assert "script:" not in text
    assert "Selection hint:" in text
