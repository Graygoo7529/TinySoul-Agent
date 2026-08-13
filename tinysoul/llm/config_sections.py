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
from .config_types import ProviderAdapterKind, ProviderApiStyle, ProviderSpec
from .errors import LLMContractError
from .model_chain import ModelChain, RetryPolicy, TaskSpec, TaskSpecTable
from .models import ModelCapability, ModelRegistry, ModelSpec
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
                {"enabled", "adapter", "api_style", "base_url", "api_key_envs"},
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
                        adapter=enum_value(
                            ProviderAdapterKind,
                            required_str(
                                provider_table,
                                "adapter",
                                key=f"llm.providers.{provider_id}",
                            ),
                            key=f"llm.providers.{provider_id}.adapter",
                        ),
                        api_style=enum_value(
                            ProviderApiStyle,
                            required_str(
                                provider_table,
                                "api_style",
                                key=f"llm.providers.{provider_id}",
                            ),
                            key=f"llm.providers.{provider_id}.api_style",
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
                    "provider",
                    "provider_model",
                    "context_window_tokens",
                    "capabilities",
                    "adapter_options",
                    "request_overrides",
                },
                key=f"llm.models.{model_id}",
            )
            provider_id = required_str(
                model_table,
                "provider",
                key=f"llm.models.{model_id}",
            )
            if provider_id not in providers:
                raise ConfigError(
                    "Model references unknown provider",
                    key=f"llm.models.{model_id}.provider",
                    value=provider_id,
                )
            provider_model = required_str(
                model_table,
                "provider_model",
                key=f"llm.models.{model_id}",
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
                _validate_adapter_option_keys(
                    adapter_options.values,
                    adapter=providers[provider_id].adapter,
                    provider_model=provider_model,
                    key=f"llm.models.{model_id}.adapter_options",
                )
                registry.register(
                    ModelSpec(
                        id=model_id,
                        provider_id=provider_id,
                        provider_model=provider_model,
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
                    "max_retries_per_model",
                    "retry_wait_seconds",
                    "switch_wait_seconds",
                    "max_cycles",
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
                    if models.get(model_id).provider_id in enabled_provider_ids
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
                max_retries_per_model=optional_int(
                    table,
                    "max_retries_per_model",
                    default=defaults.max_retries_per_model,
                    key=key,
                ),
                retry_wait_seconds=optional_float(
                    table,
                    "retry_wait_seconds",
                    default=defaults.retry_wait_seconds,
                    key=key,
                ),
                switch_wait_seconds=optional_float(
                    table,
                    "switch_wait_seconds",
                    default=defaults.switch_wait_seconds,
                    key=key,
                ),
                max_cycles=optional_int_or_none(
                    table,
                    "max_cycles",
                    default=defaults.max_cycles,
                    key=key,
                ),
                prefer_successful_model_seconds=optional_float_or_none(
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


_ADAPTER_OPTION_KEYS: dict[ProviderAdapterKind, frozenset[str]] = {
    ProviderAdapterKind.GENERIC: frozenset(),
    ProviderAdapterKind.OPENAI: frozenset(
        {
            "reasoning_effort",
            "reasoning_summary",
            "reasoning_keep",
            "verbosity",
            "prompt_cache_retention",
            "service_tier",
            "store",
            "top_p",
        }
    ),
    ProviderAdapterKind.KIMI: frozenset(
        {"thinking", "reasoning_effort", "reasoning_keep", "top_p"}
    ),
    ProviderAdapterKind.DEEPSEEK: frozenset(
        {"thinking", "reasoning_effort", "reasoning_keep"}
    ),
    ProviderAdapterKind.GLM: frozenset(
        {
            "thinking",
            "reasoning_keep",
            "reasoning_effort",
            "do_sample",
            "top_p",
            "request_id",
            "user_id",
        }
    ),
    ProviderAdapterKind.MINIMAX: frozenset(
        {"thinking", "reasoning_split", "reasoning_keep", "top_p"}
    ),
}


def _validate_adapter_option_keys(
    options: Mapping[str, object],
    *,
    adapter: ProviderAdapterKind,
    provider_model: str,
    key: str,
) -> None:
    reject_unknown_keys(
        options,
        _ADAPTER_OPTION_KEYS[adapter],
        key=key,
    )
    if "thinking" in options:
        _validate_thinking_option(
            options["thinking"],
            adapter=adapter,
            key=f"{key}.thinking",
        )
    for option_key, value in options.items():
        _validate_adapter_option_value(
            option_key,
            value,
            adapter=adapter,
            provider_model=provider_model,
            key=f"{key}.{option_key}",
        )


def _validate_adapter_option_value(
    option_key: str,
    value: object,
    *,
    adapter: ProviderAdapterKind,
    provider_model: str,
    key: str,
) -> None:
    if option_key == "reasoning_keep":
        if adapter is ProviderAdapterKind.OPENAI:
            allowed = {"none", "encrypted"}
        else:
            allowed = {"none", "content"}
        if not isinstance(value, str) or value not in allowed:
            raise ConfigError(
                "Adapter reasoning_keep is incompatible with the selected adapter",
                key=key,
                value=value,
                expected=" | ".join(sorted(allowed)),
            )
        return
    if option_key == "thinking" and adapter is ProviderAdapterKind.KIMI:
        if _is_kimi_k3(provider_model):
            raise ConfigError(
                "Kimi K3 does not accept the K2.x thinking option",
                key=key,
                value=value,
            )
        return
    if option_key == "reasoning_effort":
        if adapter is ProviderAdapterKind.DEEPSEEK:
            allowed = {"high", "max"}
        elif adapter is ProviderAdapterKind.KIMI:
            if not _is_kimi_k3(provider_model):
                raise ConfigError(
                    "Kimi reasoning_effort requires a K3 provider model",
                    key=key,
                    value=value,
                )
            allowed = {"max"}
        else:
            _require_non_empty_string(value, key=key)
            return
        if value not in allowed:
            raise ConfigError(
                "Adapter reasoning_effort is invalid",
                key=key,
                value=value,
                expected=" | ".join(sorted(allowed)),
            )
        return
    if option_key == "reasoning_summary":
        if value not in {"auto", "concise", "detailed"}:
            raise ConfigError(
                "OpenAI reasoning_summary is invalid",
                key=key,
                value=value,
                expected="auto | concise | detailed",
            )
        return
    if option_key in {
        "verbosity",
        "prompt_cache_retention",
        "service_tier",
        "request_id",
        "user_id",
    }:
        _require_non_empty_string(value, key=key)
        return
    if option_key in {"store", "do_sample", "reasoning_split"}:
        if not isinstance(value, bool):
            raise ConfigError(
                "Adapter option must be a boolean",
                key=key,
                value=value,
                expected="bool",
            )
        return
    if option_key == "top_p":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(
                "Adapter option must be a number",
                key=key,
                value=value,
                expected="float",
            )


def _require_non_empty_string(value: object, *, key: str) -> None:
    if not isinstance(value, str) or not value:
        raise ConfigError(
            "Adapter option must be a non-empty string",
            key=key,
            value=value,
            expected="str",
        )


def _is_kimi_k3(provider_model: str) -> bool:
    return provider_model in {"k3", "kimi-k3"}


def _validate_thinking_option(
    value: object,
    *,
    adapter: ProviderAdapterKind,
    key: str,
) -> None:
    allowed_types = {"enabled", "disabled"}
    if adapter is ProviderAdapterKind.MINIMAX:
        allowed_types.add("adaptive")
    if isinstance(value, str):
        if value not in allowed_types:
            raise ConfigError(
                "Adapter thinking type is invalid",
                key=key,
                value=value,
                expected=" | ".join(sorted(allowed_types)),
            )
        return
    if adapter is ProviderAdapterKind.KIMI or not isinstance(value, Mapping):
        raise ConfigError(
            "Adapter thinking option has an invalid type",
            key=key,
            value=value,
            expected="string" if adapter is ProviderAdapterKind.KIMI else "string | table",
        )
    table = as_table(value, key=key)
    allowed_keys = {"type", "clear_thinking"} if adapter is ProviderAdapterKind.GLM else {"type"}
    reject_unknown_keys(table, allowed_keys, key=key)
    raw_type = table.get("type")
    if raw_type not in allowed_types:
        raise ConfigError(
                "Adapter thinking type is invalid",
            key=f"{key}.type",
            value=raw_type,
            expected=" | ".join(sorted(allowed_types)),
        )
    clear_thinking = table.get("clear_thinking")
    if clear_thinking is not None and not isinstance(clear_thinking, bool):
        raise ConfigError(
                "Adapter clear_thinking must be a boolean",
            key=f"{key}.clear_thinking",
            value=clear_thinking,
            expected="bool",
        )
