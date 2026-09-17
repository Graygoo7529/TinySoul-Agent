"""Scenario selection is bounded by grants and enforced at every Action boundary."""

from dataclasses import replace
from typing import cast

import pytest

from tests.action_helpers import FunctionActionEngineBuilder
from tinysoul.infra.config import ConfigError
from tinysoul.kernel.action.config import ActionPolicy, parse_action_policy
from tinysoul.kernel.action.core.catalog import ActionCatalog
from tinysoul.kernel.action.core.errors import ActionContractError
from tinysoul.kernel.action.core.specs import (
    ActionBackendKind, ActionBackendSpec, ActionDomainSpec, ActionRuntimeSpec,
    ActionSemanticSpec, ActionSpec, ActionToolSpec,
)
from tinysoul.llm.tools import ToolCallRecord, ToolKind
from tinysoul.runtime import RunScope


def _catalog() -> ActionCatalog:
    return ActionCatalog(
        domains=(ActionDomainSpec(name="notes", description="Read and organize notes."),),
        actions=tuple(ActionSpec(
            name=name, domain="notes",
            tool=ActionToolSpec(name=name, description=name, schema={
                "type": "object", "properties": {}, "additionalProperties": False,
            }),
            semantic=ActionSemanticSpec(), runtime=ActionRuntimeSpec(),
            backend=ActionBackendSpec(kind=ActionBackendKind.NATIVE, handler=name),
        ) for name in ("notes.read", "notes.organize")),
    )


def _builder(catalog: ActionCatalog, effects: list[str]) -> FunctionActionEngineBuilder:
    def execute(execution, context):
        effects.append(execution.call.action_name)
        return {}

    builder = FunctionActionEngineBuilder(catalog)
    for action in catalog.actions():
        builder.register_function(action.name, execute)
    return builder


async def test_action_override_isolated_from_other_views_and_enforced_before_effects() -> None:
    catalog, effects = _catalog(), []
    full = _builder(catalog, effects).build()
    restricted = _builder(catalog, effects).with_policy(parse_action_policy({
        "domains": {"notes": False}, "actions": {"notes.read": True},
    }, key="scenario.actions")).build()
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
        restricted.normalize((ToolCallRecord("two", "notes.read", {}, ToolKind.ACTION),)).calls,
        scope=RunScope(),
    ).batch
    execution = allowed.executions[0]
    tampered = replace(allowed, executions=(replace(execution, action=replace(
        execution.action, backend=ActionBackendSpec(kind=ActionBackendKind.NATIVE, handler="notes.organize"),
    )),))
    with pytest.raises(ActionContractError):
        await restricted.run_batch(tampered)
    assert effects == []
    await restricted.run_batch(allowed)
    assert effects == ["notes.read"]


def test_policy_cannot_expand_grants_or_enable_unsupported_backend() -> None:
    catalog = _catalog()
    with pytest.raises(ConfigError):
        (_builder(catalog, []).include_actions("notes.read")
         .with_policy(ActionPolicy(actions=(("notes.organize", True),))).build())
    engine = (_builder(catalog, []).mark_actions_unsupported("notes.organize")
              .with_policy(ActionPolicy(actions=(("notes.organize", True), ("notes.read", False))))
              .build())
    assert not engine.action_identifiers()
    actions = engine.catalog_json()["actions"]
    assert isinstance(actions, list)
    by_name = {item["id"]: item for item in actions if isinstance(item, dict)}
    assert by_name["notes.read"]["supported"] is True
    assert by_name["notes.read"]["available"] is False
    assert by_name["notes.organize"]["supported"] is False
    assert by_name["notes.organize"]["available"] is False


@pytest.mark.parametrize("value", [
    {"domains": {"missing": True}}, {"actions": {"missing.action": False}},
    {"actions": {"notes.read": "yes"}}, {"actions": []}, {"unknown": {}},
])
def test_policy_rejects_unknown_or_invalid_dynamic_selection(value: object) -> None:
    with pytest.raises(ConfigError):
        policy = parse_action_policy(value, key="scenario.actions")
        _builder(_catalog(), []).with_policy(policy).build()


def test_policy_constructor_rejects_malformed_pairs_without_builtin_error() -> None:
    with pytest.raises(ConfigError):
        ActionPolicy(actions=cast(tuple[tuple[str, bool], ...], (("notes.read",),)))
