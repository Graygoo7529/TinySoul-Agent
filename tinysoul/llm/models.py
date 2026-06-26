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
    TOOL_CALLING = "tool_calling"
    REASONING_OUTPUT = "reasoning_output"
    PROMPT_CACHE = "prompt_cache"


@dataclass(frozen=True)
class ProviderRequestOverrides:
    """Model-level overrides for provider-neutral request settings."""

    temperature: float | None = None
    max_output_tokens: int | None = None


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

    def request_overrides(self) -> ProviderRequestOverrides:
        value = self.values.get("request_overrides")
        if value is None:
            return ProviderRequestOverrides()
        if not isinstance(value, Mapping):
            raise TypeError("request_overrides must be a table")
        items: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("request_overrides keys must be strings")
            items[key] = item
        known_keys = {"temperature", "max_output_tokens"}
        unknown_keys = sorted(key for key in items if key not in known_keys)
        if unknown_keys:
            names = ", ".join(unknown_keys)
            raise ValueError(f"Unsupported request_overrides keys: {names}")
        return ProviderRequestOverrides(
            temperature=_optional_float(items, "temperature"),
            max_output_tokens=_optional_int(items, "max_output_tokens"),
        )

    def provider_values(self) -> dict[str, object]:
        return {
            str(key): value
            for key, value in self.values.items()
            if key != "request_overrides"
        }


def _optional_float(table: Mapping[str, object], key: str) -> float | None:
    value = table.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{key} must be a number")
    return float(value)


def _optional_int(table: Mapping[str, object], key: str) -> int | None:
    value = table.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{key} must be an integer")
    return value


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

