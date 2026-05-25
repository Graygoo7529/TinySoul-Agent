"""Configuration merging and default resolution for LLM provider layer.

Provides merge_config() to apply per-request overrides onto pool-level configs,
and resolve_defaults() to fill None values with framework-wide defaults.
"""

from __future__ import annotations

from dataclasses import fields, replace
from typing import Any

from tinysoul.infra.config import defaults as d
from tinysoul.trap import ConfigError

from .config import ChatConfig, EmbedConfig, ImageConfig, ModelConfig

# Fields that identify a model in the pool. These must never be overridden
# per-request because doing so would bypass the failover semantics.
_IDENTITY_FIELDS = frozenset({
    "provider",
    "model",
    "model_type",
    "capabilities",
    "api_key",
    "base_url",
})


def merge_config(
    base: ModelConfig,
    override: ChatConfig | EmbedConfig | ImageConfig | None,
) -> ModelConfig:
    """Apply a request-level override onto a pool-level base config.

    Rules:
    - Override fields that are not None replace base fields.
    - None means "not set" on both sides.
    - Identity fields are silently ignored if present in override
      (they simply don't exist on ChatConfig/EmbedConfig/ImageConfig).

    Args:
        base: The pool-level ModelConfig.
        override: Per-request override (ChatConfig, EmbedConfig, or ImageConfig).

    Returns:
        A new ModelConfig with overrides applied.
    """
    if override is None:
        return base

    kwargs: dict[str, Any] = {}
    for f in fields(override):
        val = getattr(override, f.name)
        if f.name == "extra_params":
            if val:
                kwargs[f.name] = {**base.extra_params, **val}
            continue
        if val is not None and f.name not in _IDENTITY_FIELDS:
            kwargs[f.name] = val

    return replace(base, **kwargs)


def resolve_defaults(config: ModelConfig) -> ModelConfig:
    """Replace None values in a ModelConfig with framework-wide defaults.

    This should be called after merge_config() so that any explicit overrides
    are preserved and only unset fields receive defaults.

    Args:
        config: A ModelConfig potentially containing None values.

    Returns:
        A new ModelConfig with all None generation parameters filled in.
    """
    kwargs: dict[str, Any] = {}

    if config.temperature is None:
        kwargs["temperature"] = d.DEFAULT_TEMPERATURE
    if config.max_tokens is None:
        kwargs["max_tokens"] = d.DEFAULT_MAX_TOKENS
    if config.enable_thinking is None:
        kwargs["enable_thinking"] = False
    if config.max_retries is None:
        kwargs["max_retries"] = d.DEFAULT_MAX_RETRIES
    if config.base_retry_delay is None:
        kwargs["base_retry_delay"] = d.DEFAULT_BASE_RETRY_DELAY
    if config.timeout is None:
        kwargs["timeout"] = d.DEFAULT_LLM_TIMEOUT

    if kwargs:
        return replace(config, **kwargs)
    return config
