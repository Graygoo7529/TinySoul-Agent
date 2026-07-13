from __future__ import annotations

from pathlib import Path

import pytest

from tinysoul.infra.config import ConfigEnvironment, ConfigError
from tinysoul.llm.config import LLMConfigParser, ProviderAdapterKind, ProviderApiStyle
from tinysoul.llm.provider.factory import build_provider_registry
from tinysoul.llm.models import ModelCapability
from tinysoul.llm.reasoning import ReasoningKeep
from tinysoul.llm.requests import TaskProfile
from tinysoul.llm.responses import AnswerFormat
from tinysoul.llm.tools import ToolUse


def test_llm_config_parses_project_config_files() -> None:
    environment = ConfigEnvironment.from_project_root(Path("."))

    config = LLMConfigParser().parse(environment.section_tree("llm"))

    kimi_provider = config.provider("kimi")
    assert kimi_provider.api_style is ProviderApiStyle.OPENAI_CHAT
    assert kimi_provider.base_url == "https://api.moonshot.cn/v1"
    assert kimi_provider.api_key_envs == ("KIMI_API_KEY", "MOONSHOT_API_KEY")

    proxy_provider = config.provider("sublyx_proxy")
    assert proxy_provider.enabled is True
    assert proxy_provider.adapter is ProviderAdapterKind.OPENAI
    assert config.provider("openai").enabled is False

    openai_model = config.models.get("gpt_5_5")
    assert openai_model.provider_id == "sublyx_proxy"
    assert openai_model.provider_model == "gpt-5.5"
    assert openai_model.supports(ModelCapability.IMAGE_INPUT)
    assert openai_model.supports(ModelCapability.IMAGE_REMOTE_URL)
    assert openai_model.supports(ModelCapability.TOOL_CALLING)
    assert openai_model.supports(ModelCapability.PROMPT_CACHE)
    assert openai_model.provider_options.reasoning_keep() is ReasoningKeep.ENCRYPTED
    assert openai_model.provider_options.values == {
        "reasoning_keep": "encrypted",
        "prompt_cache_retention": "24h",
        "verbosity": "medium",
        "reasoning_effort": "high",
        "reasoning_summary": "auto",
    }

    kimi_model = config.models.get("kimi_k2_7")
    assert kimi_model.provider_id == "kimi"
    assert kimi_model.provider_model == "kimi-k2.7-code"
    assert kimi_model.supports(ModelCapability.IMAGE_INPUT)
    assert kimi_model.supports(ModelCapability.TOOL_CALLING)
    assert kimi_model.supports(ModelCapability.PROMPT_CACHE)
    assert kimi_model.provider_options.reasoning_keep() is ReasoningKeep.CONTENT
    assert kimi_model.provider_options.values == {
        "reasoning_keep": "content",
        "thinking": "enabled",
        "request_overrides": {
            "temperature": 1.0,
        },
    }
    assert kimi_model.provider_options.request_overrides().temperature == pytest.approx(
        1.0
    )
    assert kimi_model.provider_options.request_overrides().max_output_tokens is None

    deepseek_model = config.models.get("deepseek_v4")
    assert deepseek_model.provider_id == "deepseek"
    assert deepseek_model.provider_model == "deepseek-v4-pro"
    assert deepseek_model.supports(ModelCapability.TOOL_CALLING)
    assert deepseek_model.provider_options.reasoning_keep() is ReasoningKeep.CONTENT
    assert deepseek_model.provider_options.values == {
        "thinking": "enabled",
        "reasoning_effort": "high",
        "reasoning_keep": "content",
    }

    glm_model = config.models.get("glm_5_1")
    assert glm_model.provider_id == "glm"
    assert glm_model.provider_model == "glm-5.1"
    assert glm_model.supports(ModelCapability.TOOL_CALLING)
    assert glm_model.provider_options.reasoning_keep() is ReasoningKeep.CONTENT
    assert glm_model.provider_options.values == {
        "reasoning_keep": "content",
        "thinking": "enabled",
    }

    minimax_provider = config.provider("minimax")
    assert minimax_provider.api_style is ProviderApiStyle.OPENAI_CHAT
    assert minimax_provider.base_url == "https://api.minimaxi.com/v1"

    minimax_model = config.models.get("minimax_m3")
    assert minimax_model.provider_id == "minimax"
    assert minimax_model.provider_model == "MiniMax-M3"
    assert minimax_model.supports(ModelCapability.IMAGE_INPUT)
    assert minimax_model.supports(ModelCapability.IMAGE_REMOTE_URL)
    assert minimax_model.supports(ModelCapability.TOOL_CALLING)
    assert not minimax_model.supports(ModelCapability.JSON_OBJECT_OUTPUT)
    assert minimax_model.provider_options.reasoning_keep() is ReasoningKeep.CONTENT
    assert minimax_model.provider_options.values == {
        "reasoning_keep": "content",
        "thinking": "adaptive",
        "reasoning_split": True,
    }

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
    assert framework.settings.answer_format is AnswerFormat.JSON_OBJECT
    assert framework.settings.tool_use is ToolUse.DISABLED
    assert framework.settings.temperature == pytest.approx(0.6)
    assert framework.settings.max_output_tokens == 4096

    llm_action = config.tasks.get(TaskProfile.LLM_ACTION)
    assert llm_action.settings.temperature == pytest.approx(0.3)
    assert llm_action.settings.max_output_tokens == 2048

    home_maintenance = config.tasks.get(TaskProfile.HOME_MAINTENANCE)
    assert home_maintenance.settings.answer_format is AnswerFormat.JSON_OBJECT
    assert home_maintenance.settings.tool_use is ToolUse.DISABLED
    assert home_maintenance.settings.temperature == pytest.approx(0.2)
    assert home_maintenance.settings.max_output_tokens == 256


def test_llm_config_rejects_model_with_unknown_provider() -> None:
    tree = {
        "providers": {
            "kimi": {
                "enabled": True,
                "adapter": "kimi",
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
                "enabled": True,
                "adapter": "kimi",
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
                "enabled": True,
                "adapter": "kimi",
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


def test_provider_options_rejects_unknown_reasoning_keep() -> None:
    tree = {
        "providers": {
            "kimi": {
                "enabled": True,
                "adapter": "kimi",
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
                "provider_options": {"reasoning_keep": "forever"},
            }
        },
        "tasks": {
            "framework": {
                "models": ["kimi_k2_7"],
            }
        },
    }

    with pytest.raises(ConfigError):
        LLMConfigParser().parse(tree)


def test_llm_config_rejects_invalid_request_override() -> None:
    tree = {
        "providers": {
            "kimi": {
                "enabled": True,
                "adapter": "kimi",
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
                "provider_options": {
                    "request_overrides": {"temperature": True},
                },
            }
        },
        "tasks": {
            "framework": {
                "models": ["kimi_k2_7"],
            }
        },
    }

    with pytest.raises(ConfigError):
        LLMConfigParser().parse(tree)


def test_llm_config_rejects_invalid_enum_values_at_parse_time() -> None:
    tree = {
        "providers": {
            "kimi": {
                "enabled": True,
                "adapter": "kimi",
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
                "answer_format": "yaml",
            }
        },
    }

    with pytest.raises(ConfigError) as error:
        LLMConfigParser().parse(tree)

    assert error.value.key == "llm.tasks.framework.answer_format"


def test_llm_config_rejects_invalid_retry_policy_at_parse_time() -> None:
    tree = {
        "providers": {
            "kimi": {
                "enabled": True,
                "adapter": "kimi",
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
                "max_retries_per_model": 0,
            }
        },
    }

    with pytest.raises(ConfigError) as error:
        LLMConfigParser().parse(tree)

    assert error.value.key == "llm.tasks.framework"


def test_llm_config_rejects_task_required_capability_missing_from_chain_model() -> None:
    tree = {
        "providers": {
            "kimi": {
                "enabled": True,
                "adapter": "kimi",
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


def test_llm_config_rejects_unknown_nested_provider_option_key() -> None:
    tree = {
        "providers": {
            "glm": {
                "enabled": True,
                "adapter": "glm",
                "api_style": "openai_chat",
                "base_url": "https://open.bigmodel.cn/api/paas/v4",
                "api_key_envs": ["GLM_API_KEY"],
            }
        },
        "models": {
            "glm_model": {
                "provider": "glm",
                "provider_model": "glm-model",
                "capabilities": ["text_input"],
                "provider_options": {
                    "thinking": {
                        "type": "enabled",
                        "clear_thikning": True,
                    }
                },
            }
        },
        "tasks": {"framework": {"models": ["glm_model"]}},
    }

    with pytest.raises(ConfigError) as error:
        LLMConfigParser().parse(tree)

    assert error.value.key.endswith("thinking.clear_thikning")


def test_disabled_provider_is_filtered_without_resolving_its_credential() -> None:
    tree = {
        "providers": {
            "disabled": {
                "enabled": False,
                "adapter": "generic",
                "api_style": "openai_chat",
                "base_url": "https://disabled.example/v1",
                "api_key_envs": ["DISABLED_API_KEY"],
            },
            "enabled": {
                "enabled": True,
                "adapter": "generic",
                "api_style": "openai_chat",
                "base_url": "https://enabled.example/v1",
                "api_key_envs": ["ENABLED_API_KEY"],
            },
        },
        "models": {
            "disabled_model": {
                "provider": "disabled",
                "provider_model": "disabled-model",
                "capabilities": ["text_input"],
            },
            "enabled_model": {
                "provider": "enabled",
                "provider_model": "enabled-model",
                "capabilities": ["text_input"],
            },
        },
        "tasks": {
            "framework": {
                "models": ["disabled_model", "enabled_model"],
            }
        },
    }

    config = LLMConfigParser().parse(tree)
    registry = build_provider_registry(
        config.providers,
        env={"ENABLED_API_KEY": "configured"},
    )

    assert config.tasks.get("framework").chain.model_ids == ("enabled_model",)
    assert registry.get("enabled").provider_id == "enabled"
