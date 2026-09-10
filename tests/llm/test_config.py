from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from tinysoul.app import ProjectConfigProfile
from tinysoul.infra.config import ConfigEnvironment, ConfigError
from tinysoul.llm.adapter_types import AdapterKind
from tinysoul.llm.config import LLMConfigParser, ProviderCredentialState
from tinysoul.llm.models import ModelCapability
from tinysoul.llm.provider.factory import build_provider_registry
from tinysoul.llm.reasoning import ReasoningKeep
from tinysoul.llm.requests import TaskProfile
from tests.support.project import copy_initialized_project


def test_llm_config_parses_development_profile_files(tmp_path: Path) -> None:
    root = tmp_path / "development-project"
    copy_initialized_project(root, config_profile=ProjectConfigProfile.DEVELOPMENT)
    config = LLMConfigParser().parse(ConfigEnvironment.from_project_root(root).section_tree("llm"))

    kimi_provider = config.provider("kimi")
    assert kimi_provider.adapters == (AdapterKind.KIMI,)
    assert kimi_provider.enabled is True
    assert config.provider("sublyx_proxy").adapters == (AdapterKind.OPENAI,)
    assert config.provider("orca").adapters == (
        AdapterKind.DEEPSEEK,
        AdapterKind.OPENAI,
        AdapterKind.KIMI,
        AdapterKind.GLM,
        AdapterKind.MINIMAX,
    )
    assert config.provider("wenrugou").adapters == (AdapterKind.OPENAI,)
    assert config.provider("openai").enabled is False

    model = config.models.get("gpt_5_5")
    assert tuple(binding.provider_id for binding in model.providers) == (
        "orca",
        "wenrugou",
        "sublyx_proxy",
    )
    assert model.providers[0].provider_model == "openai/gpt-5.5"
    assert model.supports(ModelCapability.TOOL_CALLING)
    assert model.adapter_options.reasoning_keep() is ReasoningKeep.ENCRYPTED

    kimi = config.models.get("kimi_k2_7")
    assert kimi.providers[0].provider_id == "orca"
    assert kimi.providers[0].provider_model == "kimi/kimi-k2.7-code"
    assert kimi.adapter is AdapterKind.KIMI
    assert kimi.adapter_options.values["protocol"] == "k2"
    assert kimi.request_overrides.temperature == pytest.approx(1.0)

    deepseek_pro = config.models.get("deepseek_v4_pro")
    assert deepseek_pro.context_window_tokens == 1_000_000
    assert tuple(binding.provider_id for binding in deepseek_pro.providers) == (
        "orca",
        "deepseek",
    )
    assert config.models.get("deepseek_v4_flash").providers[0].provider_model == (
        "deepseek/deepseek-v4-flash"
    )

    framework = config.tasks.get(TaskProfile.FRAMEWORK).chain
    assert framework.model_ids == (
        "gpt_5_6_terra",
        "gpt_5_5",
        "kimi_k2_7",
        "deepseek_v4_pro",
    )
    policy = framework.retry_policy
    assert policy.max_retries_per_provider == 1
    assert policy.provider_switch_wait_seconds == pytest.approx(0.0)
    assert policy.model_switch_wait_seconds == pytest.approx(2.0)
    assert policy.prefer_successful_provider_seconds == pytest.approx(600.0)


@pytest.mark.parametrize("config_profile", tuple(ProjectConfigProfile))
def test_built_in_models_use_orca_as_primary_provider(
    tmp_path: Path,
    config_profile: ProjectConfigProfile,
) -> None:
    root = tmp_path / config_profile.value
    copy_initialized_project(root, config_profile=config_profile)
    config = LLMConfigParser().parse(
        ConfigEnvironment.from_project_root(root).section_tree("llm")
    )
    expected_remote_models = {
        "gpt_5_5": "openai/gpt-5.5",
        "gpt_5_6_sol": "openai/gpt-5.6-sol",
        "gpt_5_6_terra": "openai/gpt-5.6-terra",
        "gpt_5_6_luna": "openai/gpt-5.6-luna",
        "deepseek_v4_pro": "deepseek/deepseek-v4-pro",
        "deepseek_v4_flash": "deepseek/deepseek-v4-flash",
        "kimi_k2_7": "kimi/kimi-k2.7-code",
        "kimi_k3": "kimi/kimi-k3",
        "glm_5_1": "z-ai/glm-5.1",
        "minimax_m3": "minimax/minimax-m3",
    }

    assert set(config.models.ids()) == set(expected_remote_models)
    for model_id, remote_model in expected_remote_models.items():
        primary = config.models.get(model_id).providers[0]
        assert primary.provider_id == "orca"
        assert primary.provider_model == remote_model


def test_model_provider_chain_accepts_only_declared_adapter() -> None:
    tree = _tree(
        providers={
            "proxy": {
                "enabled": True,
                "adapters": ["openai_compatible_chat", "openai"],
                "base_url": "https://example.test/v1",
                "api_key_envs": ["API_KEY"],
            }
        },
        model={
            "adapter": "openai_compatible_chat",
            "providers": [
                {"provider": "proxy", "provider_model": "chat-model"},
            ],
        },
    )
    config = LLMConfigParser().parse(tree)
    model = config.models.get("model")
    assert model.providers[0].provider_model == "chat-model"

    cast(dict[str, dict[str, object]], tree["models"])["model"]["adapter"] = "kimi"
    with pytest.raises(ConfigError, match="not declared"):
        LLMConfigParser().parse(tree)


def test_model_rejects_unknown_provider() -> None:
    tree = _tree(
        providers={
            "proxy": {
                "enabled": True,
                "adapters": ["openai_compatible_chat"],
                "base_url": "https://example.test/v1",
                "api_key_envs": ["API_KEY"],
            }
        },
        model={
            "adapter": "openai_compatible_chat",
            "providers": [{"provider": "missing", "provider_model": "model"}],
        },
    )
    with pytest.raises(ConfigError, match="unknown provider"):
        LLMConfigParser().parse(tree)


def test_task_rejects_unknown_model() -> None:
    tree = _tree(
        providers={"fake": _provider()},
        model={
            "adapter": "openai_compatible_chat",
            "providers": [{"provider": "fake", "provider_model": "model"}],
        },
    )
    cast(dict[str, dict[str, object]], tree["tasks"])["framework"]["models"] = [
        "missing"
    ]
    with pytest.raises(ConfigError, match="unknown model"):
        LLMConfigParser().parse(tree)


@pytest.mark.parametrize("section", ("providers", "models", "tasks"))
def test_llm_config_rejects_purely_numeric_object_id(section: str) -> None:
    tree = _tree(
        providers={"fake": _provider()},
        model={
            "adapter": "openai_compatible_chat",
            "providers": [{"provider": "fake", "provider_model": "1233"}],
        },
    )
    objects = cast(dict[str, object], tree[section])
    current_id = next(iter(objects))
    objects["1233"] = objects.pop(current_id)

    with pytest.raises(ConfigError, match="purely numeric") as error:
        LLMConfigParser().parse(tree)

    assert error.value.key == f"llm.{section}.1233"


def test_retry_policy_uses_explicit_defaults() -> None:
    config = LLMConfigParser().parse(
        _tree(
            providers={"fake": _provider()},
            model={
                "adapter": "openai_compatible_chat",
                "providers": [{"provider": "fake", "provider_model": "model"}],
            },
        )
    )
    policy = config.tasks.get("framework").chain.retry_policy
    assert policy.max_retries_per_provider == 1
    assert policy.max_cycles == 10
    assert policy.prefer_successful_model_seconds == pytest.approx(600.0)


def test_task_rejects_invalid_answer_format() -> None:
    tree = _tree(
        providers={"fake": _provider()},
        model={
            "adapter": "openai_compatible_chat",
            "providers": [{"provider": "fake", "provider_model": "model"}],
        },
    )
    cast(dict[str, dict[str, object]], tree["tasks"])["framework"]["answer_format"] = "yaml"
    with pytest.raises(ConfigError) as error:
        LLMConfigParser().parse(tree)
    assert error.value.key == "llm.tasks.framework.answer_format"


def test_task_rejects_missing_required_capability() -> None:
    tree = _tree(
        providers={"fake": _provider()},
        model={
            "adapter": "openai_compatible_chat",
            "providers": [{"provider": "fake", "provider_model": "model"}],
        },
    )
    cast(dict[str, dict[str, object]], tree["tasks"])["framework"][
        "required_capabilities"
    ] = ["image_input"]
    with pytest.raises(ConfigError, match="lacks required capabilities"):
        LLMConfigParser().parse(tree)


def test_adapter_options_reject_unknown_nested_key() -> None:
    tree = _tree(
        providers={"glm": {**_provider(), "adapters": ["glm"]}},
        model={
            "adapter": "glm",
            "providers": [{"provider": "glm", "provider_model": "glm-model"}],
            "adapter_options": {
                "thinking": {"type": "enabled", "clear_thikning": True}
            },
        },
    )
    with pytest.raises(ConfigError) as error:
        LLMConfigParser().parse(tree)
    assert error.value.key.endswith("thinking.clear_thikning")


def test_deepseek_adapter_options_accept_low_reasoning_effort() -> None:
    tree = _tree(
        providers={"deepseek": {**_provider(), "adapters": ["deepseek"]}},
        model={
            "adapter": "deepseek",
            "providers": [
                {"provider": "deepseek", "provider_model": "deepseek-v4-flash"}
            ],
            "adapter_options": {"reasoning_effort": "low"},
        },
    )

    model = LLMConfigParser().parse(tree).models.get("model")

    assert model.adapter_options.values["reasoning_effort"] == "low"


def test_llm_config_requires_model_context_window() -> None:
    tree = _tree(
        providers={"fake": _provider()},
        model={"adapter": "openai_compatible_chat", "providers": [{"provider": "fake", "provider_model": "model"}]},
    )
    del cast(dict[str, dict[str, object]], tree["models"])["model"]["context_window_tokens"]
    with pytest.raises(ConfigError) as error:
        LLMConfigParser().parse(tree)
    assert error.value.key == "llm.models.model.context_window_tokens"


def test_llm_config_rejects_unknown_adapter_option() -> None:
    tree = _tree(
        providers={"glm": {**_provider(), "adapters": ["glm"]}},
        model={
            "adapter": "glm",
            "providers": [{"provider": "glm", "provider_model": "glm-model"}],
            "adapter_options": {"unknown": True},
        },
    )
    with pytest.raises(ConfigError):
        LLMConfigParser().parse(tree)


def test_retry_policy_rejects_old_or_negative_values() -> None:
    tree = _tree(providers={"fake": _provider()}, model={"adapter": "openai_compatible_chat", "providers": [{"provider": "fake", "provider_model": "model"}]})
    tasks = cast(dict[str, dict[str, object]], tree["tasks"])
    tasks["framework"]["max_retries_per_provider"] = -1
    with pytest.raises(ConfigError):
        LLMConfigParser().parse(tree)
    tasks["framework"].pop("max_retries_per_provider")
    tasks["framework"]["max_retries_per_model"] = 1
    with pytest.raises(ConfigError):
        LLMConfigParser().parse(tree)


def test_retry_policy_rejects_non_finite_preference_window() -> None:
    tree = _tree(
        providers={"fake": _provider()},
        model={
            "adapter": "openai_compatible_chat",
            "providers": [{"provider": "fake", "provider_model": "model"}],
        },
    )
    tasks = cast(dict[str, dict[str, object]], tree["tasks"])
    tasks["framework"]["prefer_successful_provider_seconds"] = float("inf")

    with pytest.raises(ConfigError, match="finite non-negative number") as error:
        LLMConfigParser().parse(tree)

    assert error.value.key == "llm.tasks.framework"


def test_disabled_provider_stays_in_task_chain_without_requiring_credential() -> None:
    tree = {
        "providers": {
            "disabled": {**_provider(), "enabled": False, "api_key_envs": ["DISABLED_KEY"]},
            "enabled": {
                **_provider(),
                "api_key_envs": ["PRIMARY_KEY", "ENABLED_KEY"],
            },
        },
        "models": {
            "disabled_model": {"adapter": "openai_compatible_chat", "providers": [{"provider": "disabled", "provider_model": "disabled"}], "context_window_tokens": 262144, "capabilities": ["text_input"]},
            "enabled_model": {"adapter": "openai_compatible_chat", "providers": [{"provider": "enabled", "provider_model": "enabled"}], "context_window_tokens": 262144, "capabilities": ["text_input"]},
        },
        "tasks": {"framework": {"models": ["disabled_model", "enabled_model"]}},
    }
    config = LLMConfigParser().parse(tree)
    assert config.tasks.get("framework").chain.model_ids == (
        "disabled_model",
        "enabled_model",
    )
    statuses = config.provider_credential_statuses(
        {"PRIMARY_KEY": "  ", "ENABLED_KEY": " configured "}
    )
    assert statuses[0].state is ProviderCredentialState.MISSING
    assert statuses[1].state is ProviderCredentialState.CONFIGURED

    with pytest.raises(ConfigError, match="cannot be enabled") as error:
        config.validate_enabled_provider_credentials({})
    assert error.value.key == "llm.providers.enabled.api_key_envs"

    config.validate_enabled_provider_credentials(
        {"PRIMARY_KEY": "  ", "ENABLED_KEY": " configured "}
    )
    registry = build_provider_registry(
        config.providers,
        env={"ENABLED_KEY": "configured"},
    )
    assert registry.get("enabled", AdapterKind.OPENAI_COMPATIBLE_CHAT).provider_id == "enabled"


def _provider() -> dict[str, object]:
    return {
        "enabled": True,
        "adapters": ["openai_compatible_chat"],
        "base_url": "https://example.test/v1",
        "api_key_envs": ["API_KEY"],
    }


def _tree(*, providers: dict[str, object], model: dict[str, object]) -> dict[str, object]:
    complete_model = {
        "context_window_tokens": 262144,
        "capabilities": ["text_input"],
        **model,
    }
    return {
        "providers": providers,
        "models": {"model": complete_model},
        "tasks": {"framework": {"models": ["model"]}},
    }
