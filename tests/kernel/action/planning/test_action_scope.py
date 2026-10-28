from __future__ import annotations

from tests.support.actions import sample_catalog

from collections.abc import Mapping
from dataclasses import replace
from typing import cast

import pytest

from tinysoul.kernel.action.errors import ActionContractError
from tinysoul.kernel.action.catalog.catalog import ActionCatalog
from tinysoul.kernel.action.execution.preparation import ActionExecutionBuilder
from tinysoul.kernel.action.planning.normalization import ActionCallNormalizer
from tinysoul.kernel.action.planning.scope import (
    ActionDomainPromptRenderer,
    Phase1DomainScopeBuilder,
    Phase2ActionScopeBuilder,
)
from tinysoul.kernel.action.catalog.specs import ActionDomainSpec
from tinysoul.infra.json import JsonValue
from tinysoul.llm.protocol.tools import ToolCallRecord, ToolKind
from tinysoul.runtime import RunScope


@pytest.mark.parametrize(
    ("intent", "expected", "valid"),
    [
        ("  Write the script.\nRun it later.  ", "Write the script.\nRun it later.", True),
        ("", "", True),
        (" \n", "", True),
        (None, "", False),
        (42, "", False),
    ],
)
def test_domain_selection_normalizes_optional_cycle_intent(
    intent: JsonValue, expected: str, valid: bool
) -> None:
    selection = Phase1DomainScopeBuilder().normalize_selection(
        sample_catalog(),
        (
            ToolCallRecord(
                "select", "select_action_domains",
                {"domains": ["workspace"], "intent": intent}, ToolKind.CONTROL,
            ),
        ),
    )
    assert selection.intent == expected
    assert bool(selection.feedback) is not valid
    if not valid:
        assert not selection.selected_domains


def test_domain_selection_allows_absent_intent() -> None:
    absent = Phase1DomainScopeBuilder().normalize_selection(
        sample_catalog(),
        (
            ToolCallRecord(
                "select", "select_action_domains", {"domains": ["core"]},
                ToolKind.CONTROL,
            ),
        ),
    )
    assert absent.selected_domains == ("core",) and absent.intent == ""


def test_phase1_scope_exposes_domain_control_tool() -> None:
    catalog = sample_catalog()

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
    assert "execution" in enum
    assert "x-tinysoul-domains" not in tools[0].parameters


def test_phase1_domain_selection_normalizer_belongs_to_action() -> None:
    catalog = sample_catalog()

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
    catalog = sample_catalog()

    scope = Phase2ActionScopeBuilder().build(
        catalog,
        selected_domains=("core",),
    )

    tools = scope.visible_tools()
    assert {tool.name for tool in tools} == {
        action.name for action in catalog.actions_in_domain("core")
    }
    assert all(tool.kind is ToolKind.ACTION for tool in tools)
    assert all(tool.description for tool in tools)


@pytest.mark.parametrize("maximum", [7, 19])
def test_catalog_values_reach_tools_validation_and_execution(maximum: int) -> None:
    baseline = sample_catalog()
    original = baseline.get_action("core.answer")
    description = f"Configured operation with maximum {maximum}"
    parameter_description = f"Configured count up to {maximum}"
    action = replace(
        original,
        tool=replace(
            original.tool,
            description=description,
            schema={
                "type": "object",
                "properties": {
                    "count": {
                        "type": "integer",
                        "maximum": maximum,
                        "description": parameter_description,
                    },
                },
                "required": ["count"],
                "additionalProperties": False,
            },
        ),
        semantic=replace(original.semantic, use_when=(f"user condition {maximum}",)),
        runtime=replace(original.runtime, timeout_seconds=float(maximum)),
    )
    catalog = ActionCatalog(domains=baseline.domains(), actions=(action,))
    tool = (
        Phase2ActionScopeBuilder()
        .build(catalog, selected_domains=("core",))
        .visible_tools()[0]
    )
    assert description in tool.description
    assert action.semantic.use_when[0] in tool.description
    assert tool.parameters == action.tool.schema
    call = ToolCallRecord(
        id="configured",
        name=action.name,
        arguments={"count": maximum + 1},
        kind=ToolKind.ACTION,
    )
    invalid = ActionCallNormalizer().normalize((call,), catalog=catalog)
    assert not invalid.calls
    failure = invalid.results[0].failure
    assert failure is not None
    assert failure.reason == "invalid_action_params"
    assert "count" in failure.feedback
    assert str(maximum) in failure.feedback
    valid = ActionCallNormalizer().normalize(
        (replace(call, arguments={"count": maximum}),),
        catalog=catalog,
    )
    batch = ActionExecutionBuilder().build_batch(
        valid.calls,
        catalog=catalog,
        scope=RunScope(),
    )
    assert batch.executions[0].framework.timeout_seconds == maximum


def test_phase2_scope_rejects_domain_without_actions() -> None:
    catalog = _empty_domain_catalog()

    with pytest.raises(ActionContractError, match="at least one action"):
        Phase2ActionScopeBuilder().build(
            catalog,
            selected_domains=("script",),
        )


def test_phase2_scope_prepare_returns_phase_result_for_domain_without_actions() -> None:
    catalog = _empty_domain_catalog()

    preparation = Phase2ActionScopeBuilder().prepare(
        catalog,
        selected_domains=("script",),
    )

    assert preparation.tool_scope is None
    assert preparation.phase_results[0].stage.value == "scope"
    assert preparation.phase_results[0].frame_data["selected_domains"] == ["script"]


def test_domain_prompt_renderer_lists_actionable_domains() -> None:
    catalog = sample_catalog()

    text = ActionDomainPromptRenderer().render(catalog)

    for domain in catalog.domains():
        assert domain.name in text
        assert domain.description in text
        assert domain.selection_hint in text


def _empty_domain_catalog() -> ActionCatalog:
    return ActionCatalog(
        domains=(ActionDomainSpec(name="script", description="No actions."),),
        actions=(),
    )
