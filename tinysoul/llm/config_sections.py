"""Section parsers for LLM configuration."""

from __future__ import annotations

from collections.abc import Mapping

from tinysoul.infra.config import ConfigError, reject_unknown_keys

from .config_helpers import (
    as_table,
    enum_value,
    optional_adapter_options,
    optional_capability_set,
    optional_float,
    optional_float_or_none,
    optional_int,
    optional_int_or_none,
    optional_request_overrides,
    optional_str,
    required_bool,
    required_capability_set,
    required_int,
    required_str,
    required_str_list,
)
from .adapter import adapter_spec
from .adapter_types import AdapterKind
from .config_types import ProviderSpec
from .errors import LLMContractError
from .model_chain import ModelChain, RetryPolicy, TaskSpec, TaskSpecTable
from .models import ModelCapability, ModelProviderBinding, ModelRegistry, ModelSpec
from .requests import CallSettings
from .responses import AnswerFormat
from .tools import ToolUse


def _validate_object_id(value: str, *, key: str) -> None:
    if not value or value != value.strip() or "." in value:
        raise ConfigError(
            "LLM configuration object ID must not contain dots or outer whitespace",
            key=key,
            value=value,
            expected="non-empty identifier without '.'",
        )


class ProviderConfigParser:
    """Parse configured LLM provider definitions."""

    def parse(self, table: Mapping[str, object]) -> list[ProviderSpec]:
        providers: list[ProviderSpec] = []
        for provider_id, value in table.items():
            _validate_object_id(provider_id, key=f"llm.providers.{provider_id}")
            provider_table = as_table(value, key=f"llm.providers.{provider_id}")
            reject_unknown_keys(
                provider_table,
                {"enabled", "adapters", "base_url", "api_key_envs"},
                key=f"llm.providers.{provider_id}",
            )
            try:
                providers.append(
                    ProviderSpec(
                        id=provider_id,
                        enabled=required_bool(
                            provider_table,
                            "enabled",
                            key=f"llm.providers.{provider_id}",
                        ),
                        adapters=tuple(
                            enum_value(
                                AdapterKind,
                                adapter,
                                key=f"llm.providers.{provider_id}.adapters",
                            )
                            for adapter in required_str_list(
                                provider_table,
                                "adapters",
                                key=f"llm.providers.{provider_id}",
                                non_empty=True,
                            )
                        ),
                        base_url=required_str(
                            provider_table,
                            "base_url",
                            key=f"llm.providers.{provider_id}",
                        ),
                        api_key_envs=tuple(
                            required_str_list(
                                provider_table,
                                "api_key_envs",
                                key=f"llm.providers.{provider_id}",
                                non_empty=True,
                            )
                        ),
                    )
                )
            except LLMContractError as exc:
                raise ConfigError(
                    str(exc),
                    key=f"llm.providers.{provider_id}",
                ) from exc
        return providers


class ModelConfigParser:
    """Parse configured LLM model definitions."""

    def parse(
        self,
        table: Mapping[str, object],
        *,
        providers: Mapping[str, ProviderSpec],
    ) -> ModelRegistry:
        registry = ModelRegistry()
        for model_id, value in table.items():
            _validate_object_id(model_id, key=f"llm.models.{model_id}")
            model_table = as_table(value, key=f"llm.models.{model_id}")
            reject_unknown_keys(
                model_table,
                {
                    "adapter",
                    "providers",
                    "context_window_tokens",
                    "capabilities",
                    "adapter_options",
                    "request_overrides",
                },
                key=f"llm.models.{model_id}",
            )
            adapter = enum_value(
                AdapterKind,
                required_str(
                    model_table,
                    "adapter",
                    key=f"llm.models.{model_id}",
                ),
                key=f"llm.models.{model_id}.adapter",
            )
            provider_bindings = self._parse_provider_bindings(
                model_table,
                model_id=model_id,
                providers=providers,
                adapter=adapter,
            )
            try:
                adapter_options = optional_adapter_options(
                    model_table,
                    key=f"llm.models.{model_id}",
                )
                request_overrides = optional_request_overrides(
                    model_table,
                    key=f"llm.models.{model_id}",
                )
                adapter_spec(adapter).validate_options(
                    adapter_options.values,
                    key=f"llm.models.{model_id}.adapter_options",
                )
                registry.register(
                    ModelSpec(
                        id=model_id,
                        adapter=adapter,
                        providers=provider_bindings,
                        context_window_tokens=required_int(
                            model_table,
                            "context_window_tokens",
                            key=f"llm.models.{model_id}",
                        ),
                        capabilities=required_capability_set(
                            model_table,
                            "capabilities",
                            key=f"llm.models.{model_id}",
                        ),
                        adapter_options=adapter_options,
                        request_overrides=request_overrides,
                    )
                )
            except LLMContractError as exc:
                raise ConfigError(str(exc), key=f"llm.models.{model_id}") from exc
        return registry

    def _parse_provider_bindings(
        self,
        table: Mapping[str, object],
        *,
        model_id: str,
        providers: Mapping[str, ProviderSpec],
        adapter: AdapterKind,
    ) -> tuple[ModelProviderBinding, ...]:
        value = table.get("providers")
        if not isinstance(value, list) or not value:
            raise ConfigError(
                "Model providers must be a non-empty list",
                key=f"llm.models.{model_id}.providers",
                value=value,
                expected="non-empty list[table]",
            )
        bindings: list[ModelProviderBinding] = []
        for index, item in enumerate(value):
            key = f"llm.models.{model_id}.providers.{index}"
            binding_table = as_table(item, key=key)
            reject_unknown_keys(binding_table, {"provider", "provider_model"}, key=key)
            provider_id = required_str(binding_table, "provider", key=key)
            provider = providers.get(provider_id)
            if provider is None:
                raise ConfigError(
                    "Model references unknown provider",
                    key=f"{key}.provider",
                    value=provider_id,
                )
            if adapter not in provider.adapters:
                raise ConfigError(
                    "Model adapter is not declared by provider",
                    key=f"llm.models.{model_id}.adapter",
                    value=adapter.value,
                    expected=f"provider {provider_id} adapters",
                )
            try:
                bindings.append(
                    ModelProviderBinding(
                        provider_id=provider_id,
                        provider_model=required_str(binding_table, "provider_model", key=key),
                    )
                )
            except LLMContractError as exc:
                raise ConfigError(str(exc), key=key) from exc
        if len({binding.provider_id for binding in bindings}) != len(bindings):
            raise ConfigError(
                "Model providers must be unique",
                key=f"llm.models.{model_id}.providers",
            )
        return tuple(bindings)


class TaskConfigParser:
    """Parse configured LLM task profiles."""

    def parse(
        self,
        table: Mapping[str, object],
        *,
        models: ModelRegistry,
        enabled_provider_ids: frozenset[str] | None = None,
    ) -> TaskSpecTable:
        tasks = TaskSpecTable()
        for profile, value in table.items():
            _validate_object_id(profile, key=f"llm.tasks.{profile}")
            task_table = as_table(value, key=f"llm.tasks.{profile}")
            reject_unknown_keys(
                task_table,
                {
                    "models",
                    "required_capabilities",
                    "answer_format",
                    "tool_use",
                    "temperature",
                    "max_output_tokens",
                    "max_retries_per_provider",
                    "retry_wait_seconds",
                    "provider_switch_wait_seconds",
                    "model_switch_wait_seconds",
                    "max_cycles",
                    "prefer_successful_provider_seconds",
                    "prefer_successful_model_seconds",
                },
                key=f"llm.tasks.{profile}",
            )
            model_ids = tuple(
                required_str_list(
                    task_table,
                    "models",
                    key=f"llm.tasks.{profile}",
                    non_empty=True,
                )
            )
            for model_id in model_ids:
                if not models.has(model_id):
                    raise ConfigError(
                        "Task references unknown model",
                        key=f"llm.tasks.{profile}.models",
                        value=model_id,
                    )
            if enabled_provider_ids is not None:
                model_ids = tuple(
                    model_id
                    for model_id in model_ids
                    if any(
                        binding.provider_id in enabled_provider_ids
                        for binding in models.get(model_id).providers
                    )
                )
                if not model_ids:
                    raise ConfigError(
                        "Task has no models from enabled providers",
                        key=f"llm.tasks.{profile}.models",
                    )
            required_capabilities = optional_capability_set(
                task_table,
                "required_capabilities",
                key=f"llm.tasks.{profile}",
            )
            self._validate_task_required_capabilities(
                profile=profile,
                model_ids=model_ids,
                models=models,
                required_capabilities=required_capabilities,
            )
            retry_policy = self._parse_retry_policy(
                task_table,
                key=f"llm.tasks.{profile}",
            )
            tasks.register(
                TaskSpec(
                    profile=profile,
                    chain=self._parse_model_chain(
                        profile=profile,
                        model_ids=model_ids,
                        retry_policy=retry_policy,
                    ),
                    settings=CallSettings(
                        answer_format=enum_value(
                            AnswerFormat,
                            optional_str(
                                task_table,
                                "answer_format",
                                default=AnswerFormat.JSON_OBJECT.value,
                                key=f"llm.tasks.{profile}",
                            ),
                            key=f"llm.tasks.{profile}.answer_format",
                        ),
                        tool_use=enum_value(
                            ToolUse,
                            optional_str(
                                task_table,
                                "tool_use",
                                default=ToolUse.DISABLED.value,
                                key=f"llm.tasks.{profile}",
                            ),
                            key=f"llm.tasks.{profile}.tool_use",
                        ),
                        temperature=optional_float_or_none(
                            task_table,
                            "temperature",
                            default=None,
                            key=f"llm.tasks.{profile}",
                        ),
                        max_output_tokens=optional_int_or_none(
                            task_table,
                            "max_output_tokens",
                            default=None,
                            key=f"llm.tasks.{profile}",
                        ),
                        required_capabilities=required_capabilities,
                    ),
                )
            )
        return tasks

    def _parse_retry_policy(
        self,
        table: Mapping[str, object],
        *,
        key: str,
    ) -> RetryPolicy:
        try:
            defaults = RetryPolicy()
            return RetryPolicy(
                max_retries_per_provider=optional_int(
                    table,
                    "max_retries_per_provider",
                    default=defaults.max_retries_per_provider,
                    key=key,
                ),
                retry_wait_seconds=optional_float(
                    table,
                    "retry_wait_seconds",
                    default=defaults.retry_wait_seconds,
                    key=key,
                ),
                provider_switch_wait_seconds=optional_float(
                    table,
                    "provider_switch_wait_seconds",
                    default=defaults.provider_switch_wait_seconds,
                    key=key,
                ),
                model_switch_wait_seconds=optional_float(
                    table,
                    "model_switch_wait_seconds",
                    default=defaults.model_switch_wait_seconds,
                    key=key,
                ),
                max_cycles=optional_int_or_none(
                    table,
                    "max_cycles",
                    default=defaults.max_cycles,
                    key=key,
                ),
                prefer_successful_provider_seconds=optional_float(
                    table,
                    "prefer_successful_provider_seconds",
                    default=defaults.prefer_successful_provider_seconds,
                    key=key,
                ),
                prefer_successful_model_seconds=optional_float(
                    table,
                    "prefer_successful_model_seconds",
                    default=defaults.prefer_successful_model_seconds,
                    key=key,
                ),
            )
        except LLMContractError as exc:
            raise ConfigError(str(exc), key=key) from exc

    def _parse_model_chain(
        self,
        *,
        profile: str,
        model_ids: tuple[str, ...],
        retry_policy: RetryPolicy,
    ) -> ModelChain:
        try:
            return ModelChain(
                profile=profile,
                model_ids=model_ids,
                retry_policy=retry_policy,
            )
        except LLMContractError as exc:
            raise ConfigError(str(exc), key=f"llm.tasks.{profile}.models") from exc

    def _validate_task_required_capabilities(
        self,
        *,
        profile: str,
        model_ids: tuple[str, ...],
        models: ModelRegistry,
        required_capabilities: frozenset[ModelCapability],
    ) -> None:
        if not required_capabilities:
            return
        for model_id in model_ids:
            model = models.get(model_id)
            missing = [
                capability
                for capability in required_capabilities
                if not model.supports(capability)
            ]
            if missing:
                names = ", ".join(capability.value for capability in missing)
                raise ConfigError(
                    "Task model lacks required capabilities",
                    key=f"llm.tasks.{profile}.required_capabilities",
                    value=f"{model_id}: {names}",
                )
