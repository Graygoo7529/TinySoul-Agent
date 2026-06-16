from __future__ import annotations

from pathlib import Path

import pytest

from tinysoul.infra.config import ConfigEnvironment, ConfigError
from tinysoul.llm.config import LLMConfigParser, ProviderApiStyle
from tinysoul.llm.model_chain import TaskProfile
from tinysoul.llm.models import ModelCapability


def test_llm_config_parses_project_config_files() -> None:
    environment = ConfigEnvironment.from_project_root(Path("."))

    config = LLMConfigParser().parse(environment.section_tree("llm"))

    kimi_provider = config.provider("kimi")
    assert kimi_provider.api_style is ProviderApiStyle.OPENAI_CHAT
    assert kimi_provider.base_url == "https://api.moonshot.cn/v1"
    assert kimi_provider.api_key_envs == ("KIMI_API_KEY", "MOONSHOT_API_KEY")

    kimi_model = config.models.get("kimi_k2_7")
    assert kimi_model.provider_id == "kimi"
    assert kimi_model.provider_model == "kimi-k2.7-code"
    assert kimi_model.supports(ModelCapability.IMAGE_INPUT)
    assert kimi_model.supports(ModelCapability.PROMPT_CACHE)

    chain = config.chains.get(TaskProfile.FRAMEWORK_DEFAULT)
    assert chain.model_ids == ("kimi_k2_7", "deepseek_v4", "glm_5_1", "minimax_m3")
    assert chain.retry_policy.max_retries_per_model == 2
    assert chain.retry_policy.prefer_successful_model_seconds == pytest.approx(600.0)


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
        "chains": {
            "framework.default": {
                "models": ["bad"],
            }
        },
    }

    with pytest.raises(ConfigError):
        LLMConfigParser().parse(tree)


def test_llm_config_rejects_chain_with_unknown_model() -> None:
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
        "chains": {
            "framework.default": {
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
        "chains": {
            "framework.default": {
                "models": ["kimi_k2_7"],
            }
        },
    }

    config = LLMConfigParser().parse(tree)

    chain = config.chains.get("framework.default")
    assert chain.retry_policy.max_cycles == 10
    assert chain.retry_policy.max_retries_per_model == 1
