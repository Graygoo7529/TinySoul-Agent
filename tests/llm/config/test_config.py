from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from tests.support.project import copy_initialized_project
from tinysoul.gateway.project.initializer import ProjectConfigProfile
from tinysoul.infra.config import ConfigEnvironment, ConfigError
from tinysoul.llm.adapter.factory import build_provider_registry
from tinysoul.llm.config.loader import LLMConfigParser, ProviderCredentialState
from tinysoul.llm.protocol.adapter_types import AdapterKind, ApiMode
from tinysoul.llm.protocol.models import ModelCapability
from tinysoul.llm.protocol.reasoning import NativeReplayMode


def test_llm_config_parses_development_profile_files(tmp_path: Path) -> None:
    root = tmp_path / "development-project"
    copy_initialized_project(
        root,
        config_profile=ProjectConfigProfile.DEVELOPMENT,
    )
    config = LLMConfigParser().parse(
        ConfigEnvironment.from_project_root(root).section_tree("llm")
    )

    kimi_provider = config.provider("kimi")
    assert tuple(endpoint.api_mode for endpoint in kimi_provider.endpoints) == (
        ApiMode.OPENAI_CHAT,
    )
    assert kimi_provider.enabled is True
    assert tuple(
        endpoint.api_mode for endpoint in config.provider("sublyx-proxy").endpoints
    ) == (ApiMode.OPENAI_RESPONSES,)
    assert {endpoint.api_mode for endpoint in config.provider("orca").endpoints} == {
        ApiMode.OPENAI_CHAT,
        ApiMode.OPENAI_RESPONSES,
    }
    assert tuple(
        endpoint.api_mode for endpoint in config.provider("wenrugou").endpoints
    ) == (ApiMode.OPENAI_RESPONSES,)
    assert config.provider("openai").enabled is False

    model = config.models.get("gpt-sol")
    assert model.supports(ModelCapability.TOOL_CALLING)
    assert model.adapter_options.native_replay_mode() is NativeReplayMode.ENCRYPTED

    kimi = config.models.get("kimi-coding-latest")
    assert kimi.adapter is AdapterKind.KIMI
    assert kimi.adapter_options.values["variant"] == "k2"
    assert kimi.request_overrides.temperature is None

    deepseek_pro = config.models.get("deepseek-pro")
    assert deepseek_pro.context_window_tokens == 1_048_576
    deepseek_flash = config.models.get("deepseek-flash")
    assert deepseek_flash.supports(ModelCapability.IMAGE_INPUT)
    assert deepseek_flash.supports(ModelCapability.IMAGE_REMOTE_URL)

    frame_stage1 = config.tasks.get("frame-stage1").chain
    config.tasks.get("frame-stage2")
    assert not config.tasks.has("memory_daily")
    policy = frame_stage1.retry_policy
    assert policy.max_retries_per_provider == 1
    assert policy.provider_switch_wait_seconds == pytest.approx(0.0)
    assert policy.model_switch_wait_seconds == pytest.approx(2.0)
    assert policy.prefer_successful_provider_seconds == pytest.approx(600.0)


def test_model_provider_chain_matches_api_mode() -> None:
    tree = _tree(
        providers={
            "proxy": {
                "enabled": True,
                "endpoints": {
                    "openai-chat": {"base_url": "https://example.test/v1"},
                    "openai-responses": {"base_url": "https://example.test/v1"},
                },
                "api_key_envs": ["API_KEY"],
            }
        },
        model={
            "adapter": "openai-chat",
            "providers": [
                {"provider": "proxy", "provider_model": "chat-model"},
            ],
        },
    )
    config = LLMConfigParser().parse(tree)
    model = config.models.get("model")
    assert model.providers[0].provider_model == "chat-model"

    cast(dict[str, dict[str, object]], tree["models"])["model"]["adapter"] = "deepseek"
    assert (
        LLMConfigParser().parse(tree).models.get("model").adapter
        is AdapterKind.DEEPSEEK
    )
    cast(dict[str, dict[str, object]], tree["models"])["model"]["adapter"] = (
        "anthropic-messages"
    )
    with pytest.raises(ConfigError, match="API mode"):
        LLMConfigParser().parse(tree)


def test_model_rejects_unknown_provider() -> None:
    tree = _tree(
        providers={
            "proxy": {
                "enabled": True,
                "endpoints": {"openai-chat": {"base_url": "https://example.test/v1"}},
                "api_key_envs": ["API_KEY"],
            }
        },
        model={
            "adapter": "openai-chat",
            "providers": [{"provider": "missing", "provider_model": "model"}],
        },
    )
    with pytest.raises(ConfigError, match="unknown provider"):
        LLMConfigParser().parse(tree)


def test_task_rejects_unknown_model() -> None:
    tree = _tree(
        providers={"fake": _provider()},
        model={
            "adapter": "openai-chat",
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
            "adapter": "openai-chat",
            "providers": [{"provider": "fake", "provider_model": "1233"}],
        },
    )
    objects = cast(dict[str, object], tree[section])
    current_id = next(iter(objects))
    objects["1233"] = objects.pop(current_id)

    with pytest.raises(ConfigError, match="lower-kebab-case") as error:
        LLMConfigParser().parse(tree)

    assert error.value.key == f"llm.{section}.1233"


def test_retry_policy_uses_explicit_defaults() -> None:
    config = LLMConfigParser().parse(
        _tree(
            providers={"fake": _provider()},
            model={
                "adapter": "openai-chat",
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
            "adapter": "openai-chat",
            "providers": [{"provider": "fake", "provider_model": "model"}],
        },
    )
    cast(dict[str, dict[str, object]], tree["tasks"])["framework"]["answer_format"] = (
        "yaml"
    )
    with pytest.raises(ConfigError) as error:
        LLMConfigParser().parse(tree)
    assert error.value.key == "llm.tasks.framework.answer_format"


def test_task_rejects_missing_required_capability() -> None:
    tree = _tree(
        providers={"fake": _provider()},
        model={
            "adapter": "openai-chat",
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
        providers={"glm": _provider()},
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
    assert error.value.key.endswith("adapter_options.thinking")


def test_deepseek_adapter_options_accept_low_reasoning_effort() -> None:
    tree = _tree(
        providers={"deepseek": _provider()},
        model={
            "adapter": "deepseek",
            "providers": [
                {"provider": "deepseek", "provider_model": "deepseek-v4-flash"}
            ],
            "adapter_options": {"choices": {"reasoning_effort": ["low", "high"]}},
            "reasoning_effort": "low",
        },
    )

    model = LLMConfigParser().parse(tree).models.get("model")

    assert model.reasoning_effort == "low"


def test_llm_config_requires_model_context_window() -> None:
    tree = _tree(
        providers={"fake": _provider()},
        model={
            "adapter": "openai-chat",
            "providers": [{"provider": "fake", "provider_model": "model"}],
        },
    )
    del cast(dict[str, dict[str, object]], tree["models"])["model"][
        "context_window_tokens"
    ]
    with pytest.raises(ConfigError) as error:
        LLMConfigParser().parse(tree)
    assert error.value.key == "llm.models.model.context_window_tokens"


def test_llm_config_rejects_unknown_adapter_option() -> None:
    tree = _tree(
        providers={"glm": _provider()},
        model={
            "adapter": "glm",
            "providers": [{"provider": "glm", "provider_model": "glm-model"}],
            "adapter_options": {"unknown": True},
        },
    )
    with pytest.raises(ConfigError):
        LLMConfigParser().parse(tree)


def test_retry_policy_rejects_old_or_negative_values() -> None:
    tree = _tree(
        providers={"fake": _provider()},
        model={
            "adapter": "openai-chat",
            "providers": [{"provider": "fake", "provider_model": "model"}],
        },
    )
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
            "adapter": "openai-chat",
            "providers": [{"provider": "fake", "provider_model": "model"}],
        },
    )
    tasks = cast(dict[str, dict[str, object]], tree["tasks"])
    tasks["framework"]["prefer_successful_provider_seconds"] = float("inf")

    with pytest.raises(ConfigError, match="finite non-negative number") as error:
        LLMConfigParser().parse(tree)

    assert error.value.key == "llm.tasks.framework"


async def test_disabled_provider_stays_in_task_chain_without_requiring_credential() -> (
    None
):
    tree = {
        "providers": {
            "disabled": {
                **_provider(),
                "enabled": False,
                "api_key_envs": ["DISABLED_KEY"],
            },
            "enabled": {
                **_provider(),
                "api_key_envs": ["PRIMARY_KEY", "ENABLED_KEY"],
            },
        },
        "models": {
            "disabled-model": {
                "adapter": "openai-chat",
                "providers": [{"provider": "disabled", "provider_model": "disabled"}],
                "context_window_tokens": 262144,
                "capabilities": ["text_input"],
            },
            "enabled-model": {
                "adapter": "openai-chat",
                "providers": [{"provider": "enabled", "provider_model": "enabled"}],
                "context_window_tokens": 262144,
                "capabilities": ["text_input"],
            },
        },
        "tasks": {"framework": {"models": ["disabled-model", "enabled-model"]}},
    }
    config = LLMConfigParser().parse(tree)
    assert config.tasks.get("framework").chain.model_ids == (
        "disabled-model",
        "enabled-model",
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
    registry = await build_provider_registry(
        config.providers,
        models=config.models,
        env={"ENABLED_KEY": "configured"},
    )
    assert registry.get("enabled", AdapterKind.OPENAI_CHAT).provider_id == "enabled"
    await registry.close()


@pytest.mark.parametrize("adapter", ["anthropic-messages", "google-generate-content"])
async def test_configured_modes_load_with_runtime_clients(adapter: str) -> None:
    config = LLMConfigParser().parse(
        _tree(
            providers={
                "future": {
                    "enabled": True,
                    "api_key_envs": ["FUTURE_KEY"],
                    "endpoints": {adapter: {"base_url": "https://example.test"}},
                }
            },
            model={
                "adapter": adapter,
                "providers": [
                    {"provider": "future", "provider_model": "vendor/latest"}
                ],
                "adapter_options": {"thinking": "adaptive"}
                if adapter == "anthropic-messages"
                else {"choices": {"reasoning_effort": ["high"]}},
            },
        )
    )
    registry = await build_provider_registry(
        config.providers, models=config.models, env={"FUTURE_KEY": "test"}
    )
    assert registry.has("future", AdapterKind(adapter))
    assert config.tasks.get("framework").chain.model_ids == ("model",)
    await registry.close()


def test_selected_effort_must_belong_to_model_candidates() -> None:
    tree = _tree(
        providers={"proxy": _provider()},
        model={
            "adapter": "openai-chat",
            "providers": [{"provider": "proxy", "provider_model": "remote"}],
            "adapter_options": {
                "choices": {"reasoning_effort": ["custom-high", "custom-max"]}
            },
            "reasoning_effort": "high",
        },
    )
    with pytest.raises(ConfigError, match="reasoning_effort"):
        LLMConfigParser().parse(tree)


@pytest.mark.parametrize(
    ("thinking", "effort", "display", "valid"),
    [
        ("adaptive", "max", "updates", True),
        ("between_tools", "high", None, True),
        ("between_tools", "max", None, False),
        ("adaptive", "high", "updates", False),
        ("disabled", "high", None, False),
    ],
)
def test_model_choice_rules_intersect_selected_values(
    thinking: str, effort: str, display: str | None, valid: bool
) -> None:
    options: dict[str, object] = {
        "thinking": thinking,
        "choices": {"reasoning_effort": ["high", "max"]},
        "choice_rules": [
            {
                "when": {"thinking": "between_tools"},
                "choices": {"reasoning_effort": ["high"]},
            },
            {
                "when": {"reasoning_effort": "high"},
                "choices": {"thinking_display": ["omitted"]},
            },
            {"when": {"thinking": "disabled"}, "choices": {"reasoning_effort": []}},
        ],
    }
    if display is not None:
        options["thinking_display"] = display
    tree = _tree(
        providers={
            "proxy": {
                **_provider(),
                "endpoints": {
                    "anthropic-messages": {"base_url": "https://example.test"}
                },
            }
        },
        model={
            "adapter": "anthropic-messages",
            "providers": [{"provider": "proxy", "provider_model": "remote"}],
            "adapter_options": options,
            "reasoning_effort": effort,
        },
    )
    if valid:
        config = LLMConfigParser().parse(tree)
        assert config.models.get("model").reasoning_effort == effort
    else:
        with pytest.raises(ConfigError, match="not available"):
            LLMConfigParser().parse(tree)


def _provider() -> dict[str, object]:
    return {
        "enabled": True,
        "endpoints": {"openai-chat": {"base_url": "https://example.test/v1"}},
        "api_key_envs": ["API_KEY"],
    }


def _tree(
    *, providers: dict[str, object], model: dict[str, object]
) -> dict[str, object]:
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
