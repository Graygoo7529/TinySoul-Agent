from __future__ import annotations

from pathlib import Path

import pytest

from tinysoul.infra.config import ConfigEnvironment, ConfigError
from tinysoul.llm.config import LLMConfigParser, ProviderApiStyle
from tinysoul.llm.models import ModelCapability
from tinysoul.llm.requests import TaskProfile
from tinysoul.llm.responses import ResponseContract


def test_llm_config_parses_project_config_files() -> None:
    environment = ConfigEnvironment.from_project_root(Path("."))

    config = LLMConfigParser().parse(environment.section_tree("llm"))

    kimi_provider = config.provider("kimi")
    assert kimi_provider.api_style is ProviderApiStyle.OPENAI_CHAT
    assert kimi_provider.base_url == "https://api.moonshot.cn/v1"
    assert kimi_provider.api_key_envs == ("KIMI_API_KEY", "MOONSHOT_API_KEY")

    openai_model = config.models.get("gpt_5_5")
    assert openai_model.provider_id == "openai"
    assert openai_model.provider_model == "gpt-5.5"
    assert openai_model.supports(ModelCapability.IMAGE_INPUT)
    assert openai_model.supports(ModelCapability.IMAGE_REMOTE_URL)
    assert openai_model.supports(ModelCapability.PROMPT_CACHE)
    assert openai_model.provider_options.values == {
        "prompt_cache_retention": "24h",
        "verbosity": "medium",
        "reasoning_effort": "high",
    }

    kimi_model = config.models.get("kimi_k2_7")
    assert kimi_model.provider_id == "kimi"
    assert kimi_model.provider_model == "kimi-k2.7-code"
    assert kimi_model.supports(ModelCapability.IMAGE_INPUT)
    assert kimi_model.supports(ModelCapability.PROMPT_CACHE)
    assert kimi_model.provider_options.values == {"thinking": "enabled"}

    deepseek_model = config.models.get("deepseek_v4")
    assert deepseek_model.provider_id == "deepseek"
    assert deepseek_model.provider_model == "deepseek-v4-pro"
    assert deepseek_model.provider_options.values == {
        "thinking": "enabled",
        "reasoning_effort": "high",
    }

    glm_model = config.models.get("glm_5_1")
    assert glm_model.provider_id == "glm"
    assert glm_model.provider_model == "glm-5.1"
    assert glm_model.provider_options.values == {"thinking": "enabled"}

    framework = config.tasks.get(TaskProfile.FRAMEWORK)
    assert framework.chain.model_ids == (
        "gpt_5_5",
        "kimi_k2_7",
        "deepseek_v4",
        "glm_5_1",
        "minimax_m3",
    )
    assert framework.chain.retry_policy.max_retries_per_model == 2
    assert framework.chain.retry_policy.prefer_successful_model_seconds == pytest.approx(600.0)
    assert framework.settings.response_contract is ResponseContract.JSON_OBJECT
    assert framework.settings.temperature == pytest.approx(0.6)
    assert framework.settings.max_output_tokens == 4096

    llm_action = config.tasks.get(TaskProfile.LLM_ACTION)
    assert llm_action.settings.temperature == pytest.approx(0.3)
    assert llm_action.settings.max_output_tokens == 2048


def test_llm_config_rejects_model_with_unknown_provider() -> None:
    tree = {
        "providers": {
            "kimi": {
                "api_style": "openai_chat",
                "base_url": "https://api.moonshot.cn/v1",
                "api_key_envs": ["KIMI_API_KEY"],
            }
        },
        "models": {
            "bad": {
                "provider": "missing",
                "provider_model": "model",
                "capabilities": ["text_input"],
            }
        },
        "tasks": {
            "framework": {
                "models": ["bad"],
            }
        },
    }

    with pytest.raises(ConfigError):
        LLMConfigParser().parse(tree)


def test_llm_config_rejects_task_with_unknown_model() -> None:
    tree = {
        "providers": {
            "kimi": {
                "api_style": "openai_chat",
                "base_url": "https://api.moonshot.cn/v1",
                "api_key_envs": ["KIMI_API_KEY"],
            }
        },
        "models": {
            "kimi_k2_7": {
                "provider": "kimi",
                "provider_model": "kimi-k2.7-code",
                "capabilities": ["text_input"],
            }
        },
        "tasks": {
            "framework": {
                "models": ["missing"],
            }
        },
    }

    with pytest.raises(ConfigError):
        LLMConfigParser().parse(tree)


def test_llm_config_uses_retry_defaults_when_omitted() -> None:
    tree = {
        "providers": {
            "kimi": {
                "api_style": "openai_chat",
                "base_url": "https://api.moonshot.cn/v1",
                "api_key_envs": ["KIMI_API_KEY"],
            }
        },
        "models": {
            "kimi_k2_7": {
                "provider": "kimi",
                "provider_model": "kimi-k2.7-code",
                "capabilities": ["text_input"],
            }
        },
        "tasks": {
            "framework": {
                "models": ["kimi_k2_7"],
            }
        },
    }

    config = LLMConfigParser().parse(tree)

    task = config.tasks.get("framework")
    assert task.chain.retry_policy.max_cycles == 10
    assert task.chain.retry_policy.max_retries_per_model == 1


def test_llm_config_rejects_task_required_capability_missing_from_chain_model() -> None:
    tree = {
        "providers": {
            "kimi": {
                "api_style": "openai_chat",
                "base_url": "https://api.moonshot.cn/v1",
                "api_key_envs": ["KIMI_API_KEY"],
            }
        },
        "models": {
            "text_model": {
                "provider": "kimi",
                "provider_model": "text-model",
                "capabilities": ["text_input"],
            }
        },
        "tasks": {
            "framework": {
                "models": ["text_model"],
                "required_capabilities": ["image_input"],
            }
        },
    }

    with pytest.raises(ConfigError):
        LLMConfigParser().parse(tree)
