from __future__ import annotations

from pathlib import Path

from tinysoul.action.core.loader import ActionCatalogLoader
from tinysoul.action.core.scope import Phase1DomainScopeBuilder, Phase2ActionScopeBuilder
from tinysoul.llm.tools import ToolKind


def test_phase1_scope_exposes_domain_control_tool() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/builtin"))

    scope = Phase1DomainScopeBuilder().build(catalog)

    tools = scope.visible_tools()
    assert len(tools) == 1
    assert tools[0].kind is ToolKind.CONTROL
    assert tools[0].name == "select_action_domains"
    assert "workspace" in tools[0].parameters["properties"]["domains"]["items"]["enum"]


def test_phase2_scope_exposes_selected_domain_actions_only() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/builtin"))

    scope = Phase2ActionScopeBuilder().build(
        catalog,
        selected_domains=("core",),
    )

    tools = scope.visible_tools()
    assert [tool.name for tool in tools] == ["core.answer"]
    assert tools[0].kind is ToolKind.ACTION
    assert "Use when:" in tools[0].description
