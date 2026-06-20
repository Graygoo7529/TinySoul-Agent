"""LLM model registry and capability model."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from .reasoning import ReasoningKeep


class ModelCapability(StrEnum):
    """Abstract model capability used by TinySoul routing."""

    TEXT_INPUT = "text_input"
    IMAGE_INPUT = "image_input"
    IMAGE_REMOTE_URL = "image_remote_url"
    JSON_OBJECT_OUTPUT = "json_object_output"
    REASONING_OUTPUT = "reasoning_output"
    PROMPT_CACHE = "prompt_cache"


@dataclass(frozen=True)
class ProviderOptions:
    """Provider-specific model options."""

    values: Mapping[str, object] = field(default_factory=dict)

    def reasoning_keep(self) -> ReasoningKeep:
        value = self.values.get("reasoning_keep")
        if value is None:
            return ReasoningKeep.NONE
        if isinstance(value, str):
            return ReasoningKeep(value)
        raise TypeError("reasoning_keep must be a string")


@dataclass(frozen=True)
class ModelSpec:
    """A registered model and its TinySoul-visible capabilities."""

    id: str
    provider_id: str
    provider_model: str
    capabilities: frozenset[ModelCapability] = field(
        default_factory=lambda: frozenset({ModelCapability.TEXT_INPUT})
    )
    provider_options: ProviderOptions = field(default_factory=ProviderOptions)

    def supports(self, capability: ModelCapability) -> bool:
        return capability in self.capabilities


class ModelRegistry:
    """Registry of available models."""

    def __init__(self, models: list[ModelSpec] | None = None) -> None:
        self._models: dict[str, ModelSpec] = {}
        for model in models or []:
            self.register(model)

    def register(self, model: ModelSpec) -> None:
        if model.id in self._models:
            raise ValueError(f"Model already registered: {model.id}")
        self._models[model.id] = model

    def get(self, model_id: str) -> ModelSpec:
        try:
            return self._models[model_id]
        except KeyError as exc:
            raise KeyError(f"Unknown model: {model_id}") from exc

    def has(self, model_id: str) -> bool:
        return model_id in self._models

