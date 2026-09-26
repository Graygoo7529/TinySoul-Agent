from __future__ import annotations

import pytest

from tinysoul.infra.config import ConfigError
from tinysoul.kernel.action.config import parse_action_settings
from tinysoul.kernel.action.models import (
    ModelUseRegistry,
    ModelUseDescriptor,
    ModelOperation,
    ModelImplementation,
)
from tinysoul.infra.model_services.config import ModelServicesSettings
from tinysoul.kernel.retrieval.policy import RetrievalPolicy
from tinysoul.kernel.retrieval.contracts import SourceKind, OperationKind


def _settings(**overrides):
    return parse_action_settings(
        {
            "models": {
                "bindings": [
                    {
                        "consumer": "core.answer.generate",
                        "implementation": "llm_task",
                        "target": {"task_profile": "answer"},
                        **overrides,
                    }
                ]
            }
        }
    )


def test_binding_resolves_only_declared_consumer_and_task() -> None:
    settings = _settings()
    registry = ModelUseRegistry(
        (
            ModelUseDescriptor(
                "core.answer.generate", "core.answer", ModelOperation.GENERATE
            ),
        ),
        settings.bindings,
    )
    registry.validate_targets(("answer",), ModelServicesSettings())
    assert registry.binding("core.answer.generate").task_profile == "answer"
    assert registry.projection("core.answer")[0]["operation"] == "generate"
    with pytest.raises(ConfigError):
        registry.validate_targets(("missing",), ModelServicesSettings())


@pytest.mark.parametrize(
    "override",
    [
        {"consumer": "unknown"},
        {"implementation": "structured_decision", "target": {"use": "jev"}},
    ],
)
def test_registry_rejects_unknown_consumer_or_implementation(override) -> None:
    with pytest.raises(ConfigError):
        ModelUseRegistry(
            (
                ModelUseDescriptor(
                    "core.answer.generate", "core.answer", ModelOperation.GENERATE
                ),
            ),
            _settings(**override).bindings,
        )


@pytest.mark.parametrize(
    "override",
    [
        {"target": {"use": "invalid"}},
        {"options": {"unknown": True}},
        {"options": {"max_output_tokens": 0}},
        {"implementation": "unknown"},
    ],
)
def test_binding_rejects_wrong_target_and_options(override) -> None:
    with pytest.raises(ConfigError):
        _settings(**override)


def test_old_routing_and_duplicate_bindings_are_rejected() -> None:
    with pytest.raises(ConfigError):
        parse_action_settings({"llm_action": {}})
    value = {
        "consumer": "core.answer.generate",
        "implementation": "llm_task",
        "target": {"task_profile": "answer"},
    }
    with pytest.raises(ConfigError):
        parse_action_settings({"models": {"bindings": [value, value]}})


def test_same_consumer_can_bind_decision_without_changing_action_identity() -> None:
    descriptor = ModelUseDescriptor(
        "home.search.select",
        "home.search",
        ModelOperation.SELECT,
        (ModelImplementation.LLM_TASK, ModelImplementation.STRUCTURED_DECISION),
    )
    settings = parse_action_settings(
        {
            "models": {
                "bindings": [
                    {
                        "consumer": descriptor.consumer,
                        "implementation": "structured_decision",
                        "target": {"use": "decision"},
                    }
                ]
            }
        }
    )
    registry = ModelUseRegistry((descriptor,), settings.bindings)
    assert registry.descriptor(descriptor.consumer).action_id == "home.search"
    assert registry.binding(descriptor.consumer).use == "decision"
    with pytest.raises(ConfigError):
        registry.validate_targets((), ModelServicesSettings())
    policy = RetrievalPolicy("home.search", (SourceKind.REFS,), (OperationKind.SELECT,))
    registry.validate_selected(
        actions=frozenset(),
        retrieval_policies=(policy,),
        services=ModelServicesSettings(),
        env={},
        embedding_uses={},
    )
    with pytest.raises(ConfigError):
        registry.validate_selected(
            actions=frozenset({"home.search"}),
            retrieval_policies=(policy,),
            services=ModelServicesSettings(),
            env={},
            embedding_uses={},
        )
