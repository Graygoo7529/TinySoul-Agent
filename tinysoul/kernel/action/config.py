"""Action module project settings."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from tinysoul.infra.config import ConfigError, reject_unknown_keys

from .catalog.catalog import ActionCatalog
from .catalog.specs import ActionSpec
from .models import ModelImplementation, ModelUseBinding
from tinysoul.kernel.retrieval.policy import (
    RetrievalPolicy,
    parse_retrieval_policies,
)


@dataclass(frozen=True)
class ActionSelection:
    """Resolved visibility and the exact configuration level that selected it."""

    enabled: bool
    source: str


class ActionPolicy:
    """Resolve catalog visibility without granting executable capabilities."""

    @staticmethod
    def selection(
        catalog: ActionCatalog, action: ActionSpec, scenario: str
    ) -> ActionSelection:
        domain = catalog.get_domain(action.domain)
        choices = (
            (
                action.visibility.for_scenario(scenario),
                f"action.visibility.scenarios.{scenario}",
            ),
            (
                domain.visibility.for_scenario(scenario),
                f"domain.visibility.scenarios.{scenario}",
            ),
            (action.visibility.default, "action.visibility.default"),
            (domain.visibility.default, "domain.visibility.default"),
        )
        for value, source in choices:
            if value is not None:
                return ActionSelection(value, source)
        return ActionSelection(True, "default")

    @staticmethod
    def validate(
        catalog: ActionCatalog,
        *,
        granted: frozenset[str],
        scenario: str,
        scenarios: frozenset[str],
    ) -> None:
        if scenario not in scenarios:
            raise ConfigError(
                "Unknown Action scenario", key="action.scenario", value=scenario
            )
        for spec in (*catalog.domains(), *catalog.actions()):
            if any(name not in scenarios for name, _ in spec.visibility.scenarios):
                raise ConfigError(
                    "Unknown Action visibility scenario",
                    key=f"{spec.name}.visibility.scenarios",
                )
        for action in catalog.actions():
            if (
                action.visibility.for_scenario(scenario) is True
                and action.name not in granted
            ):
                raise ConfigError(
                    "Action scenario selection cannot grant an operation",
                    key=f"{action.name}.visibility.scenarios.{scenario}",
                )


@dataclass(frozen=True)
class ActionSettings:
    """Explicit per-consumer bindings; no implicit default model route."""

    bindings: tuple[ModelUseBinding, ...] = ()
    retrieval_policies: tuple[RetrievalPolicy, ...] = ()



def parse_action_settings(tree: Mapping[str, object]) -> ActionSettings:
    reject_unknown_keys(tree, {"models", "retrieval"}, key="action")
    models = _table(tree.get("models", {}), key="action.models")
    reject_unknown_keys(models, {"bindings"}, key="action.models")
    retrieval = tree.get("retrieval", {})
    values = models.get("bindings", [])
    if not isinstance(values, list):
        raise ConfigError("Model bindings must be tables", key="action.models.bindings")
    bindings: list[ModelUseBinding] = []
    for index, value in enumerate(values):
        key = f"action.models.bindings.{index}"
        table = _table(value, key=key)
        reject_unknown_keys(
            table, {"consumer", "implementation", "target", "options"}, key=key
        )
        try:
            implementation = ModelImplementation(
                _text(table, "implementation", key=key)
            )
        except ValueError as exc:
            raise ConfigError("Unknown model implementation", key=key) from exc
        target = _table(table.get("target", {}), key=f"{key}.target")
        allowed = (
            {"task_profile"}
            if implementation is ModelImplementation.LLM_TASK
            else {"use"}
            if implementation is ModelImplementation.STRUCTURED_DECISION
            else set()
        )
        reject_unknown_keys(target, allowed, key=f"{key}.target")
        options = _table(table.get("options", {}), key=f"{key}.options")
        option_names = (
            {"max_output_tokens"}
            if implementation is ModelImplementation.LLM_TASK
            else {"relevance_threshold"}
            if implementation is ModelImplementation.STRUCTURED_DECISION
            else set()
        )
        reject_unknown_keys(options, option_names, key=f"{key}.options")
        tokens = options.get("max_output_tokens")
        threshold = options.get("relevance_threshold", 2)
        if tokens is not None and type(tokens) is not int:
            raise ConfigError("max_output_tokens must be an integer", key=key)
        if type(threshold) is not int:
            raise ConfigError("relevance_threshold must be an integer", key=key)
        bindings.append(
            ModelUseBinding(
                consumer=_text(table, "consumer", key=key),
                implementation=implementation,
                task_profile=_text(target, "task_profile", key=key)
                if "task_profile" in target
                else None,
                use=_text(target, "use", key=key) if "use" in target else None,
                max_output_tokens=tokens,
                relevance_threshold=threshold,
            )
        )
    if len({binding.consumer for binding in bindings}) != len(bindings):
        raise ConfigError("Duplicate model binding", key="action.models.bindings")
    return ActionSettings(
        tuple(bindings),
        parse_retrieval_policies(retrieval),
    )


def _table(value: object, *, key: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or any(
        not isinstance(name, str) for name in value
    ):
        raise ConfigError("Expected a table with string keys", key=key)
    return dict(cast(Mapping[str, object], value))


def _text(table: Mapping[str, object], name: str, *, key: str) -> str:
    value = table.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("Expected a nonempty string", key=f"{key}.{name}")
    return value
