"""LLM model registry and capability model."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from .errors import LLMContractError, LLMInvariantError
from .reasoning import ReasoningKeep
from .adapter_types import AdapterKind


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
class RequestOverrides:
    """Model-level overrides for provider-neutral request settings."""

    temperature: float | None = None
    max_output_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.temperature is not None:
            if isinstance(self.temperature, bool) or not isinstance(
                self.temperature, (int, float)
            ):
                raise LLMContractError(
                    "RequestOverrides.temperature must be a number or None"
                )
            object.__setattr__(self, "temperature", float(self.temperature))
        if self.max_output_tokens is not None and (
            isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or self.max_output_tokens <= 0
        ):
            raise LLMContractError(
                "RequestOverrides.max_output_tokens must be a positive integer or None"
            )


@dataclass(frozen=True)
class AdapterOptions:
    """Model-level options interpreted by the selected provider adapter."""

    values: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        items: dict[str, object] = {}
        for key, value in self.values.items():
            if not isinstance(key, str):
                raise LLMContractError("adapter option keys must be strings")
            items[key] = value
        object.__setattr__(self, "values", items)

    def reasoning_keep(self) -> ReasoningKeep:
        value = self.values.get("reasoning_keep")
        if value is None:
            return ReasoningKeep.NONE
        if isinstance(value, str):
            try:
                return ReasoningKeep(value)
            except ValueError as exc:
                raise LLMContractError(
                    "reasoning_keep must be 'none', 'content', or 'encrypted'"
                ) from exc
        raise LLMContractError("reasoning_keep must be a string")

@dataclass(frozen=True)
class ModelSpec:
    """A registered model and its TinySoul-visible capabilities."""

    id: str
    provider_id: str
    provider_model: str
    context_window_tokens: int
    capabilities: frozenset[ModelCapability] = field(
        default_factory=lambda: frozenset({ModelCapability.TEXT_INPUT})
    )
    adapter_options: AdapterOptions = field(default_factory=AdapterOptions)
    request_overrides: RequestOverrides = field(default_factory=RequestOverrides)
    adapter: AdapterKind = AdapterKind.GENERIC

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise LLMContractError("ModelSpec.id must be non-empty")
        if not isinstance(self.provider_id, str) or not self.provider_id:
            raise LLMContractError("ModelSpec.provider_id must be non-empty")
        if not isinstance(self.adapter, AdapterKind):
            raise LLMContractError("ModelSpec.adapter must be an AdapterKind")
        if not isinstance(self.provider_model, str) or not self.provider_model:
            raise LLMContractError("ModelSpec.provider_model must be non-empty")
        if (
            isinstance(self.context_window_tokens, bool)
            or not isinstance(self.context_window_tokens, int)
            or self.context_window_tokens <= 0
        ):
            raise LLMContractError(
                "ModelSpec.context_window_tokens must be a positive integer"
            )
        try:
            capabilities = frozenset(self.capabilities)
        except TypeError as exc:
            raise LLMContractError(
                "ModelSpec.capabilities must be an iterable of ModelCapability values"
            ) from exc
        if not capabilities:
            raise LLMContractError("ModelSpec.capabilities must be non-empty")
        for capability in capabilities:
            if not isinstance(capability, ModelCapability):
                raise LLMContractError(
                    "ModelSpec.capabilities must contain ModelCapability values"
                )
        object.__setattr__(self, "capabilities", capabilities)
        if not isinstance(self.adapter_options, AdapterOptions):
            raise LLMContractError(
                "ModelSpec.adapter_options must be an AdapterOptions value"
            )
        if not isinstance(self.request_overrides, RequestOverrides):
            raise LLMContractError(
                "ModelSpec.request_overrides must be a RequestOverrides value"
            )

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
            raise LLMInvariantError(f"Model already registered: {model.id}")
        self._models[model.id] = model

    def get(self, model_id: str) -> ModelSpec:
        try:
            return self._models[model_id]
        except KeyError as exc:
            raise LLMContractError(f"Unknown model: {model_id}") from exc

    def has(self, model_id: str) -> bool:
        return model_id in self._models
