"""AI model configuration for TinySoul.

Unified configuration for Chat, Embedding, and Image Generation models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class ModelType(StrEnum):
    """Type of AI model."""

    CHAT = "chat"
    EMBEDDING = "embedding"
    IMAGE_GEN = "image_gen"


class ModelCapability(StrEnum):
    """Capabilities a model may possess."""

    TEXT = "text"
    VISION = "vision"
    REASONING = "reasoning"
    TOOL_USE = "tool_use"


class LLMProfileName(StrEnum):
    """Named chat-routing profiles used by TinySoul's LLM call sites."""

    STEP1 = "step1"
    STEP2 = "step2"
    STEP3 = "step3"
    ACTION_LLM = "action_llm"


@dataclass
class ModelConfig:
    """Configuration for a single AI model in the pool.

    Used for Chat, Embedding, and Image Generation models.
    Fields specific to one model type are ignored by others.

    All generation parameters default to None, meaning "use framework default".
    The resolver layer (merge_config + resolve_defaults) fills these in.
    """

    # Identity fields — these are pool-managed and cannot be overridden per-request
    provider: str
    model: str
    model_type: ModelType = ModelType.CHAT
    capabilities: list[ModelCapability] = field(
        default_factory=lambda: [ModelCapability.TEXT]
    )

    # Auth & Endpoint
    api_key: str | None = None
    base_url: str | None = None

    # Chat-specific params (None = use framework default, resolved by resolver)
    temperature: float | None = None
    max_tokens: int | None = None
    enable_thinking: bool | None = None

    # Embedding-specific params
    dimensions: int | None = None

    # Shared params (None = use framework default)
    extra_params: dict = field(default_factory=dict)
    max_retries: int | None = None
    base_retry_delay: float | None = None
    timeout: float | None = None


@dataclass
class ChatConfig:
    """Per-request generation parameters for chat completions.

    Identity-free by design — provider, model, api_key are managed by the
    client pool and failover system. This type only carries generation params.
    """

    temperature: float | None = None
    max_tokens: int | None = None
    enable_thinking: bool | None = None
    extra_params: dict = field(default_factory=dict)
    timeout: float | None = None


@dataclass
class ChatProfile:
    """Routing and default-generation config for one chat call profile.

    ``chat_model_overrides`` maps provider name to an explicit chat model
    override, so a single profile can override models for multiple providers in
    its failover chain.
    ``required_capabilities`` is a hard filter. ``preferred_capabilities`` is a
    soft preference used to select the best default chat model per provider
    when no explicit override is configured.
    """

    provider_chain: list[str]
    required_capabilities: list[ModelCapability] = field(
        default_factory=lambda: [ModelCapability.TEXT]
    )
    preferred_capabilities: list[ModelCapability] = field(default_factory=list)
    chat_model_overrides: dict[str, "ChatModelOverride"] = field(default_factory=dict)
    config: ChatConfig = field(default_factory=ChatConfig)


@dataclass
class ChatModelOverride:
    """Explicit per-provider chat model override for a chat profile.

    ``capabilities`` may be omitted only when the override model matches an
    existing provider chat config. Unknown model names must declare
    capabilities explicitly so routing does not inherit incorrect metadata.
    """

    model: str
    capabilities: list[ModelCapability] | None = None


def normalize_profile_name(profile: LLMProfileName | str) -> str:
    """Normalize a profile enum/string to its canonical string value."""
    if isinstance(profile, LLMProfileName):
        return profile.value
    try:
        return LLMProfileName(profile).value
    except ValueError:
        return str(profile)


def build_chat_profile(raw: ChatProfile | Mapping[str, Any]) -> ChatProfile:
    """Build a ChatProfile from an existing object or settings dict."""
    if isinstance(raw, ChatProfile):
        return raw

    provider_chain = list(raw.get("provider_chain", []))
    required_capabilities = [
        c if isinstance(c, ModelCapability) else ModelCapability(str(c))
        for c in raw.get("required_capabilities", [ModelCapability.TEXT])
    ]
    preferred_capabilities = [
        c if isinstance(c, ModelCapability) else ModelCapability(str(c))
        for c in raw.get("preferred_capabilities", [])
    ]
    chat_model_overrides = {
        str(k): build_chat_model_override(v)
        for k, v in dict(raw.get("chat_model_overrides", {})).items()
    }
    raw_config = raw.get("config", {}) or {}
    config = raw_config if isinstance(raw_config, ChatConfig) else ChatConfig(**raw_config)
    return ChatProfile(
        provider_chain=provider_chain,
        required_capabilities=required_capabilities,
        preferred_capabilities=preferred_capabilities,
        chat_model_overrides=chat_model_overrides,
        config=config,
    )


def build_chat_model_override(raw: ChatModelOverride | Mapping[str, Any]) -> ChatModelOverride:
    """Build a structured chat model override from settings data."""
    if isinstance(raw, ChatModelOverride):
        return raw
    if not isinstance(raw, Mapping):
        raise TypeError("chat_model_overrides entries must be objects with a 'model' field")

    model = raw.get("model")
    if not model:
        raise ValueError("chat_model_overrides entries must include a non-empty 'model'")
    raw_capabilities = raw.get("capabilities")
    capabilities = None
    if raw_capabilities is not None:
        capabilities = [
            c if isinstance(c, ModelCapability) else ModelCapability(str(c))
            for c in raw_capabilities
        ]
    return ChatModelOverride(model=str(model), capabilities=capabilities)


def build_chat_profiles(
    raw_profiles: Mapping[str | LLMProfileName, ChatProfile | Mapping[str, Any]]
) -> dict[str, ChatProfile]:
    """Normalize a profile mapping and ensure all built-in profiles exist."""
    profiles = {
        normalize_profile_name(name): build_chat_profile(profile)
        for name, profile in raw_profiles.items()
    }
    missing = [p.value for p in LLMProfileName if p.value not in profiles]
    if missing:
        raise ValueError(f"Missing chat profile(s): {', '.join(missing)}")
    return profiles


@dataclass
class EmbedConfig:
    """Per-request parameters for text embeddings."""

    dimensions: int | None = None
    extra_params: dict = field(default_factory=dict)
    timeout: float | None = None


@dataclass
class ImageConfig:
    """Per-request parameters for image generation."""

    extra_params: dict = field(default_factory=dict)
    timeout: float | None = None
