"""LLM configuration parsing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from tinysoul.infra.config import ConfigError

from .model_chain import ModelChain, RetryPolicy, TaskSpec, TaskSpecTable
from .models import ModelCapability, ModelRegistry, ModelSpec, ProviderOptions
from .requests import CallSettings
from .responses import ResponseContract


class ProviderApiStyle(StrEnum):
    """Supported provider API styles."""

    OPENAI_CHAT = "openai_chat"
    OPENAI_RESPONSES = "openai_responses"


@dataclass(frozen=True)
class ProviderSpec:
    """Configured provider API endpoint."""

    id: str
    api_style: ProviderApiStyle
    base_url: str
    api_key_envs: tuple[str, ...]


@dataclass(frozen=True)
class LLMConfig:
    """Parsed LLM configuration."""

    providers: tuple[ProviderSpec, ...]
    models: ModelRegistry
    tasks: TaskSpecTable

    def provider(self, provider_id: str) -> ProviderSpec:
        for provider in self.providers:
            if provider.id == provider_id:
                return provider
        raise KeyError(f"Unknown provider: {provider_id}")


class LLMConfigParser:
    """Parse the LLM section from a configuration tree."""

    def parse(self, llm_tree: Mapping[str, object]) -> LLMConfig:
        providers = self._parse_providers(_required_table(llm_tree, "providers", key="llm"))
        provider_ids = {provider.id for provider in providers}
        models = self._parse_models(
            _required_table(llm_tree, "models", key="llm"),
            provider_ids=provider_ids,
        )
        tasks = self._parse_tasks(
            _required_table(llm_tree, "tasks", key="llm"),
            models=models,
        )
        return LLMConfig(
            providers=tuple(providers),
            models=models,
            tasks=tasks,
        )

    def _parse_providers(self, table: Mapping[str, object]) -> list[ProviderSpec]:
        providers: list[ProviderSpec] = []
        for provider_id, value in table.items():
            provider_table = _as_table(value, key=f"llm.providers.{provider_id}")
            providers.append(
                ProviderSpec(
                    id=provider_id,
                    api_style=ProviderApiStyle(
                        _required_str(provider_table, "api_style", key=f"llm.providers.{provider_id}")
                    ),
                    base_url=_required_str(provider_table, "base_url", key=f"llm.providers.{provider_id}"),
                    api_key_envs=tuple(
                        _required_str_list(
                            provider_table,
                            "api_key_envs",
                            key=f"llm.providers.{provider_id}",
                        )
                    ),
                )
            )
        return providers

    def _parse_models(
        self,
        table: Mapping[str, object],
        *,
        provider_ids: set[str],
    ) -> ModelRegistry:
        registry = ModelRegistry()
        for model_id, value in table.items():
            model_table = _as_table(value, key=f"llm.models.{model_id}")
            provider_id = _required_str(model_table, "provider", key=f"llm.models.{model_id}")
            if provider_id not in provider_ids:
                raise ConfigError(
                    "Model references unknown provider",
                    key=f"llm.models.{model_id}.provider",
                    value=provider_id,
                )
            registry.register(
                ModelSpec(
                    id=model_id,
                    provider_id=provider_id,
                    provider_model=_required_str(
                        model_table,
                        "provider_model",
                        key=f"llm.models.{model_id}",
                    ),
                    capabilities=frozenset(
                        ModelCapability(capability)
                        for capability in _required_str_list(
                            model_table,
                            "capabilities",
                            key=f"llm.models.{model_id}",
                        )
                    ),
                    provider_options=_optional_provider_options(
                        model_table,
                        key=f"llm.models.{model_id}",
                    ),
                )
            )
        return registry

    def _parse_tasks(
        self,
        table: Mapping[str, object],
        *,
        models: ModelRegistry,
    ) -> TaskSpecTable:
        tasks = TaskSpecTable()
        for raw_profile, value in table.items():
            profile = raw_profile
            task_table = _as_table(value, key=f"llm.tasks.{profile}")
            model_ids = tuple(
                _required_str_list(task_table, "models", key=f"llm.tasks.{profile}")
            )
            for model_id in model_ids:
                if not models.has(model_id):
                    raise ConfigError(
                        "Task references unknown model",
                        key=f"llm.tasks.{profile}.models",
                        value=model_id,
                    )
            tasks.register(
                TaskSpec(
                    profile=profile,
                    chain=ModelChain(
                        profile=profile,
                        model_ids=model_ids,
                        retry_policy=RetryPolicy(
                            max_retries_per_model=_optional_int(
                                task_table,
                                "max_retries_per_model",
                                default=RetryPolicy().max_retries_per_model,
                                key=f"llm.tasks.{profile}",
                            ),
                            retry_wait_seconds=_optional_float(
                                task_table,
                                "retry_wait_seconds",
                                default=RetryPolicy().retry_wait_seconds,
                                key=f"llm.tasks.{profile}",
                            ),
                            switch_wait_seconds=_optional_float(
                                task_table,
                                "switch_wait_seconds",
                                default=RetryPolicy().switch_wait_seconds,
                                key=f"llm.tasks.{profile}",
                            ),
                            max_cycles=_optional_int_or_none(
                                task_table,
                                "max_cycles",
                                default=RetryPolicy().max_cycles,
                                key=f"llm.tasks.{profile}",
                            ),
                            prefer_successful_model_seconds=_optional_float_or_none(
                                task_table,
                                "prefer_successful_model_seconds",
                                default=RetryPolicy().prefer_successful_model_seconds,
                                key=f"llm.tasks.{profile}",
                            ),
                        ),
                    ),
                    response_contract=ResponseContract(
                        _optional_str(
                            task_table,
                            "response_contract",
                            default=ResponseContract.JSON_OBJECT.value,
                            key=f"llm.tasks.{profile}",
                        )
                    ),
                    settings=CallSettings(
                        temperature=_optional_float_or_none(
                            task_table,
                            "temperature",
                            default=None,
                            key=f"llm.tasks.{profile}",
                        ),
                        max_output_tokens=_optional_int_or_none(
                            task_table,
                            "max_output_tokens",
                            default=None,
                            key=f"llm.tasks.{profile}",
                        ),
                    ),
                )
            )
        return tasks


def _required_table(
    table: Mapping[str, object],
    name: str,
    *,
    key: str,
) -> Mapping[str, object]:
    value = table.get(name)
    if value is None:
        raise ConfigError("Missing configuration table", key=f"{key}.{name}")
    return _as_table(value, key=f"{key}.{name}")


def _as_table(value: object, *, key: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ConfigError(
            "Configuration value must be a table",
            key=key,
            value=value,
            expected="table",
        )
    return cast(Mapping[str, object], value)


def _required_str(table: Mapping[str, object], name: str, *, key: str) -> str:
    value = table.get(name)
    if not isinstance(value, str) or not value:
        raise ConfigError(
            "Configuration value must be a non-empty string",
            key=f"{key}.{name}",
            value=value,
            expected="str",
        )
    return value


def _optional_str(
    table: Mapping[str, object],
    name: str,
    *,
    default: str,
    key: str,
) -> str:
    value = table.get(name, default)
    if not isinstance(value, str) or not value:
        raise ConfigError(
            "Configuration value must be a non-empty string",
            key=f"{key}.{name}",
            value=value,
            expected="str",
        )
    return value


def _required_str_list(table: Mapping[str, object], name: str, *, key: str) -> list[str]:
    value = table.get(name)
    if not isinstance(value, list):
        raise ConfigError(
            "Configuration value must be a list of strings",
            key=f"{key}.{name}",
            value=value,
            expected="list[str]",
        )
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ConfigError(
                "Configuration value must be a list of non-empty strings",
                key=f"{key}.{name}",
                value=value,
                expected="list[str]",
            )
        result.append(item)
    return result


def _optional_provider_options(
    table: Mapping[str, object],
    *,
    key: str,
) -> ProviderOptions:
    value = table.get("provider_options")
    if value is None:
        return ProviderOptions()
    if not isinstance(value, Mapping):
        raise ConfigError(
            "Configuration value must be a table",
            key=f"{key}.provider_options",
            value=value,
            expected="table",
        )
    return ProviderOptions(cast(Mapping[str, object], value))


def _optional_int(
    table: Mapping[str, object],
    name: str,
    *,
    default: int,
    key: str,
) -> int:
    value = table.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            "Configuration value must be an integer",
            key=f"{key}.{name}",
            value=value,
            expected="int",
        )
    return value


def _optional_int_or_none(
    table: Mapping[str, object],
    name: str,
    *,
    default: int | None,
    key: str,
) -> int | None:
    value = table.get(name, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            "Configuration value must be an integer or null",
            key=f"{key}.{name}",
            value=value,
            expected="int | null",
        )
    return value


def _optional_float(
    table: Mapping[str, object],
    name: str,
    *,
    default: float,
    key: str,
) -> float:
    value = table.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(
            "Configuration value must be a number",
            key=f"{key}.{name}",
            value=value,
            expected="float",
        )
    return float(value)


def _optional_float_or_none(
    table: Mapping[str, object],
    name: str,
    *,
    default: float | None,
    key: str,
) -> float | None:
    value = table.get(name, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(
            "Configuration value must be a number or null",
            key=f"{key}.{name}",
            value=value,
            expected="float | null",
        )
    return float(value)
