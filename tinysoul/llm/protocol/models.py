"""LLM model registry and capability model."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite

from ..errors import LLMContractError
from .adapter_types import AdapterKind
from .reasoning import NativeReplayMode


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
    top_p: float | None = None
    max_output_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.temperature is not None:
            if (
                isinstance(self.temperature, bool)
                or not isinstance(self.temperature, (int, float))
                or not isfinite(self.temperature)
                or not 0 <= self.temperature <= 2
            ):
                raise LLMContractError(
                    "RequestOverrides.temperature must be a finite number between 0 and 2"
                )
            object.__setattr__(self, "temperature", float(self.temperature))
        if self.top_p is not None:
            if (
                isinstance(self.top_p, bool)
                or not isinstance(self.top_p, (int, float))
                or not 0 <= float(self.top_p) <= 1
            ):
                raise LLMContractError("RequestOverrides.top_p must be between 0 and 1")
            object.__setattr__(self, "top_p", float(self.top_p))
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

    def native_replay_mode(self) -> NativeReplayMode:
        value = self.values.get("native_replay")
        if value is None:
            return NativeReplayMode.NONE
        if isinstance(value, str):
            try:
                return NativeReplayMode(value)
            except ValueError as exc:
                raise LLMContractError(
                    "native_replay must be 'none', 'content', 'encrypted', or 'signed'"
                ) from exc
        raise LLMContractError("native_replay must be a string")

    @property
    def variant(self) -> str | None:
        value = self.values.get("variant")
        return value if isinstance(value, str) else None

    def extra_body(self) -> Mapping[str, object] | None:
        value = self.values.get("extra_body")
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise LLMContractError("extra_body must be a JSON object")
        return value


@dataclass(frozen=True)
class ModelProviderBinding:
    """Provider route and provider-side model identifier for a model."""

    provider_id: str
    provider_model: str

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id:
            raise LLMContractError("ModelProviderBinding.provider_id must be non-empty")
        if not isinstance(self.provider_model, str) or not self.provider_model:
            raise LLMContractError(
                "ModelProviderBinding.provider_model must be non-empty"
            )


@dataclass(frozen=True)
class ModelSpec:
    """A registered model and its TinySoul-visible capabilities."""

    id: str
    providers: tuple[ModelProviderBinding, ...]
    context_window_tokens: int
    adapter: AdapterKind
    capabilities: frozenset[ModelCapability] = field(
        default_factory=lambda: frozenset({ModelCapability.TEXT_INPUT})
    )
    adapter_options: AdapterOptions = field(default_factory=AdapterOptions)
    request_overrides: RequestOverrides = field(default_factory=RequestOverrides)
    reasoning_effort: str | None = None
    family: str = ""
    collapsed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.family, str) or type(self.collapsed) is not bool:
            raise LLMContractError(
                "Model display metadata requires text family and boolean collapsed"
            )
        if not isinstance(self.id, str) or not self.id:
            raise LLMContractError("ModelSpec.id must be non-empty")
        try:
            providers = tuple(self.providers)
        except TypeError as exc:
            raise LLMContractError(
                "ModelSpec.providers must be an iterable of ModelProviderBinding values"
            ) from exc
        if not providers:
            raise LLMContractError("ModelSpec.providers must be non-empty")
        if any(
            not isinstance(provider, ModelProviderBinding) for provider in providers
        ):
            raise LLMContractError(
                "ModelSpec.providers must contain ModelProviderBinding values"
            )
        if len({provider.provider_id for provider in providers}) != len(providers):
            raise LLMContractError("ModelSpec.providers must use unique providers")
        object.__setattr__(self, "providers", providers)
        if not isinstance(self.adapter, AdapterKind):
            raise LLMContractError("ModelSpec.adapter must be an AdapterKind")
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
        if self.reasoning_effort is not None and (
            not isinstance(self.reasoning_effort, str) or not self.reasoning_effort
        ):
            raise LLMContractError(
                "ModelSpec.reasoning_effort must be a non-empty string or None"
            )
        if self.reasoning_effort is not None:
            candidates = self.adapter_options.values.get("reasoning_efforts", ())
            if (
                not isinstance(candidates, (tuple, list))
                or self.reasoning_effort not in candidates
            ):
                raise LLMContractError(
                    "reasoning_effort must belong to adapter_options.reasoning_efforts"
                )

    def supports(self, capability: ModelCapability) -> bool:
        return capability in self.capabilities
