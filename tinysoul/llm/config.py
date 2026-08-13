"""Public LLM configuration facade."""

from __future__ import annotations

from collections.abc import Mapping

from tinysoul.infra.config import reject_unknown_keys

from .config_helpers import required_table
from .config_sections import ModelConfigParser, ProviderConfigParser, TaskConfigParser
from .adapter_types import AdapterKind, ProviderApiStyle
from .config_types import LLMConfig, ProviderSpec


class LLMConfigParser:
    """Parse the LLM section from a configuration tree."""

    def __init__(
        self,
        *,
        providers: ProviderConfigParser | None = None,
        models: ModelConfigParser | None = None,
        tasks: TaskConfigParser | None = None,
    ) -> None:
        self._providers = providers or ProviderConfigParser()
        self._models = models or ModelConfigParser()
        self._tasks = tasks or TaskConfigParser()

    def parse(
        self,
        llm_tree: Mapping[str, object],
        *,
        require_enabled_providers: bool = True,
    ) -> LLMConfig:
        reject_unknown_keys(llm_tree, {"providers", "models", "tasks"}, key="llm")
        provider_specs = self._providers.parse(
            required_table(llm_tree, "providers", key="llm")
        )
        providers_by_id = {provider.id: provider for provider in provider_specs}
        model_registry = self._models.parse(
            required_table(llm_tree, "models", key="llm"),
            providers=providers_by_id,
        )
        task_specs = self._tasks.parse(
            required_table(llm_tree, "tasks", key="llm"),
            models=model_registry,
            enabled_provider_ids=(
                frozenset(
                    provider.id for provider in provider_specs if provider.enabled
                )
                if require_enabled_providers
                else None
            ),
        )
        return LLMConfig(
            providers=tuple(provider_specs),
            models=model_registry,
            tasks=task_specs,
        )


__all__ = [
    "LLMConfig",
    "LLMConfigParser",
    "ModelConfigParser",
    "AdapterKind",
    "ProviderApiStyle",
    "ProviderConfigParser",
    "ProviderSpec",
    "TaskConfigParser",
]
