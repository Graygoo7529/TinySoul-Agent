"""Scenario selection is bounded by grants and enforced at every Action boundary."""

from dataclasses import replace

import pytest

from tests.action_helpers import FunctionActionEngineBuilder
from tinysoul.infra.config import ConfigError
from tinysoul.kernel.action.config import ActionPolicy
from tinysoul.kernel.action.catalog.catalog import ActionCatalog
from tinysoul.kernel.action.errors import ActionContractError
from tinysoul.kernel.action.catalog.specs import (
    ActionExecutionSpec,
    ActionDomainSpec,
    ActionRuntimeSpec,
    ActionSemanticSpec,
    ActionSpec,
    ActionToolSpec,
    ActionVisibilitySpec,
)
from tinysoul.llm.protocol.tools import ToolCallRecord, ToolKind
from tinysoul.runtime import RunScope


def _catalog() -> ActionCatalog:
    return ActionCatalog(
        domains=(
            ActionDomainSpec(name="notes", description="Read and organize notes."),
        ),
        actions=tuple(
            ActionSpec(
                name=name,
                domain="notes",
                tool=ActionToolSpec(
                    name=name,
                    description=name,
                    schema={
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                ),
                semantic=ActionSemanticSpec(),
                runtime=ActionRuntimeSpec(),
                execution=ActionExecutionSpec(executor=name),
            )
            for name in ("notes.read", "notes.organize")
        ),
    )


def _builder(catalog: ActionCatalog, effects: list[str]) -> FunctionActionEngineBuilder:
    def execute(execution, context):
        effects.append(execution.call.action_name)
        return {}

    builder = FunctionActionEngineBuilder(catalog)
    for action in catalog.actions():
        builder.register_function(action.name, execute)
    return builder


async def test_action_override_isolated_from_other_views_and_enforced_before_effects() -> (
    None
):
    catalog, effects = _catalog(), []
    full = _builder(catalog, effects).build()
    restricted_catalog = ActionCatalog(
        domains=(
            replace(
                catalog.get_domain("notes"),
                visibility=ActionVisibilitySpec(
                    scenarios=(("user", False),),
                ),
            ),
        ),
        actions=tuple(
            replace(
                action,
                visibility=ActionVisibilitySpec(
                    scenarios=(("user", True),) if action.name == "notes.read" else (),
                ),
            )
            for action in catalog.actions()
        ),
    )
    restricted = _builder(restricted_catalog, effects).build()
    assert restricted.action_identifiers() == (("notes", "notes.read"),)
    assert len(full.action_identifiers()) == len(catalog.actions()) == 2
    tools = (ToolCallRecord("one", "notes.organize", {}, ToolKind.ACTION),)
    rejected = restricted.normalize(tools)
    assert not rejected.calls and rejected.results[0].failure is not None
    calls = full.normalize(tools).calls
    prepared = restricted.prepare_batch(calls, scope=RunScope())
    assert not prepared.batch.executions and prepared.results
    forged = full.prepare_batch(calls, scope=RunScope()).batch
    with pytest.raises(ActionContractError):
        await restricted.run_batch(forged)
    assert effects == []
    allowed = restricted.prepare_batch(
        restricted.normalize(
            (ToolCallRecord("two", "notes.read", {}, ToolKind.ACTION),)
        ).calls,
        scope=RunScope(),
    ).batch
    execution = allowed.executions[0]
    tampered = replace(
        allowed,
        executions=(
            replace(
                execution,
                action=replace(
                    execution.action,
                    execution=ActionExecutionSpec(executor="notes.organize"),
                ),
            ),
        ),
    )
    with pytest.raises(ActionContractError):
        await restricted.run_batch(tampered)
    assert effects == []
    await restricted.run_batch(allowed)
    assert effects == ["notes.read"]


@pytest.mark.parametrize(
    (
        "action_scenario",
        "domain_scenario",
        "action_default",
        "domain_default",
        "enabled",
        "source",
    ),
    (
        (False, True, True, True, False, "action.visibility.scenarios.user"),
        (True, False, False, False, True, "action.visibility.scenarios.user"),
        (None, True, False, False, True, "domain.visibility.scenarios.user"),
        (None, None, False, True, False, "action.visibility.default"),
        (None, None, None, False, False, "domain.visibility.default"),
        (None, None, None, None, True, "default"),
    ),
)
def test_visibility_priority(
    action_scenario, domain_scenario, action_default, domain_default, enabled, source
) -> None:
    catalog = _catalog()
    action = replace(
        catalog.get_action("notes.read"),
        visibility=ActionVisibilitySpec(
            default=action_default,
            scenarios=() if action_scenario is None else (("user", action_scenario),),
        ),
    )
    domain = replace(
        catalog.get_domain("notes"),
        visibility=ActionVisibilitySpec(
            default=domain_default,
            scenarios=() if domain_scenario is None else (("user", domain_scenario),),
        ),
    )
    selection = ActionPolicy.selection(
        ActionCatalog(domains=(domain,), actions=(action,)), action, "user"
    )
    assert (selection.enabled, selection.source) == (enabled, source)


def test_explicit_scenario_selection_cannot_expand_grants() -> None:
    catalog = _catalog()
    restricted = ActionCatalog(
        domains=catalog.domains(),
        actions=tuple(
            replace(
                action, visibility=ActionVisibilitySpec(scenarios=(("user", True),))
            )
            for action in catalog.actions()
        ),
    )
    with pytest.raises(ConfigError, match="cannot grant"):
        _builder(restricted, []).include_actions("notes.read").build()


def test_backend_availability_is_independent_of_visibility() -> None:
    engine = _builder(_catalog(), []).mark_actions_unsupported("notes.organize").build()
    assert engine.action_identifiers() == (("notes", "notes.read"),)
    rows = engine.catalog_json()["actions"]
    assert isinstance(rows, list)
    row = next(
        item
        for item in rows
        if isinstance(item, dict) and item["id"] == "notes.organize"
    )
    assert isinstance(row, dict)
    assert row["granted"] is True and row["available"] is False
    assert row["unavailable_reason"] == "executor_unavailable"


def test_editable_handler_cannot_borrow_another_registered_capability() -> None:
    catalog = _catalog()
    forged = ActionCatalog(
        domains=catalog.domains(),
        actions=tuple(
            (
                replace(
                    action,
                    execution=replace(action.execution, executor="notes.organize"),
                )
                if action.name == "notes.read"
                else action
            )
            for action in catalog.actions()
        ),
    )
    with pytest.raises(ActionContractError, match="execution binding"):
        _builder(forged, []).build()


def test_catalog_membership_does_not_grant_execution() -> None:
    from tinysoul.kernel.action import ActionEngineBuilder

    engine = ActionEngineBuilder(_catalog()).build()
    assert engine.action_identifiers() == ()


def test_unknown_scenario_is_rejected_even_on_a_hidden_action() -> None:
    catalog = _catalog()
    invalid = ActionCatalog(
        domains=catalog.domains(),
        actions=tuple(
            replace(
                action,
                visibility=ActionVisibilitySpec(
                    default=False, scenarios=(("typo", True),)
                ),
            )
            for action in catalog.actions()
        ),
    )
    with pytest.raises(ConfigError, match="Unknown"):
        _builder(invalid, []).build()
