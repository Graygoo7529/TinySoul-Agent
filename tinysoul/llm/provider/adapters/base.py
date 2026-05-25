"""AI provider adapters for TinySoul.

Three adapter families:
- ChatAdapter:     chat completions (supports multimodal)
- EmbeddingAdapter:text embeddings
- ImageGenAdapter: image generation

All Chat adapters use the OpenAI SDK with provider-specific overrides.
Embedding adapters also use OpenAI-compatible /embeddings where possible.
ImageGen adapters may use OpenAI images API or provider-specific HTTP.
"""

from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from typing import Any, Callable

from tinysoul.trap import ConfigError, LLMTransientError

from ..config import ModelConfig
from ..request import AIRequest
from ..response import AIResponse

# ------------------------------------------------------------------------------
# OpenAI SDK exception mapping helpers
# ------------------------------------------------------------------------------

try:
    from openai import (
        APIConnectionError as _APIConnectionError,
        APITimeoutError as _APITimeoutError,
        RateLimitError as _RateLimitError,
        AuthenticationError as _AuthenticationError,
        InternalServerError as _InternalServerError,
    )
except ImportError:
    _APIConnectionError: type[Exception] | None = None  # type: ignore[assignment]
    _APITimeoutError: type[Exception] | None = None  # type: ignore[assignment]
    _RateLimitError: type[Exception] | None = None  # type: ignore[assignment]
    _AuthenticationError: type[Exception] | None = None  # type: ignore[assignment]
    _InternalServerError: type[Exception] | None = None  # type: ignore[assignment]


_TRANSIENT_ERROR_TYPES: tuple[type[Exception], ...] = tuple(
    e for e in (_APIConnectionError, _APITimeoutError, _RateLimitError, _InternalServerError)
    if e is not None
)


def _map_openai_exception(exc: Exception, model_name: str) -> None:
    """Map an OpenAI SDK exception to a TinySoul framework exception.

    Raises:
        LLMTransientError: For network/timeout/rate-limit/server errors (should retry).
        ConfigError: For authentication failures (should abort).
        Re-raises the original exception for everything else.
    """
    if isinstance(exc, _TRANSIENT_ERROR_TYPES):
        raise LLMTransientError(str(exc), model_name=model_name) from exc

    if _AuthenticationError is not None and isinstance(exc, _AuthenticationError):
        raise ConfigError(
            f"API authentication failed for {model_name}: {exc}"
        ) from exc

    raise exc


# ------------------------------------------------------------------------------
# Adapter registry (two-dimensional: provider × model_type)
# ------------------------------------------------------------------------------

_ADAPTER_REGISTRY: dict[str, dict[str, Callable[[ModelConfig], Any]]] = {}


def register_adapter(provider: str, model_type: str):
    """Register an adapter factory. Factory receives full ModelConfig."""

    def decorator(cls):
        def factory(config: ModelConfig):
            return cls(api_key=config.api_key, base_url=config.base_url)

        _ADAPTER_REGISTRY.setdefault(provider, {})[model_type] = factory
        return cls

    return decorator


def create_adapter(config: ModelConfig) -> Any:
    """Create an adapter based on provider + model_type."""
    factory = _ADAPTER_REGISTRY.get(config.provider, {}).get(config.model_type)
    if factory is None:
        raise NotImplementedError(
            f"Provider '{config.provider}' model_type '{config.model_type}' "
            f"is not registered. Available providers: {list(_ADAPTER_REGISTRY.keys())}"
        )
    return factory(config)


# ------------------------------------------------------------------------------
# Chat Adapter
# ------------------------------------------------------------------------------


class ChatAdapter(ABC):
    """Abstract base for chat-completion adapters (multimodal-capable)."""

    @abstractmethod
    def chat(self, request: AIRequest, config: ModelConfig) -> AIResponse:
        """Execute a chat completion."""
        ...


class OpenAIChatAdapter(ChatAdapter):
    """Base chat adapter for OpenAI API-compatible providers."""

    DEFAULT_BASE_URL: str = ""
    ENV_KEY_NAMES: tuple[str, ...] = ()

    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ImportError("The 'openai' package is required. Install: pip install openai") from exc

        key = api_key or self._resolve_env_key()
        if not key:
            raise ConfigError(
                f"API key required for {self.__class__.__name__}. "
                f"Set one of: {self.ENV_KEY_NAMES}"
            )
        url = base_url or self.DEFAULT_BASE_URL or None
        self._client = OpenAI(api_key=key, base_url=url)

    def _resolve_env_key(self) -> str | None:
        for name in self.ENV_KEY_NAMES:
            key = os.environ.get(name)
            if key:
                return key
        return None

    def _build_params(self, request: AIRequest, config: ModelConfig) -> dict[str, Any]:
        """Build OpenAI SDK chat parameters.

        The *config* has already been merged with request-level overrides
        and resolved against framework defaults by _call_with_retry().
        """
        messages = (
            [*request.system, *request.messages]
            if request.system
            else request.messages
        )
        params: dict[str, Any] = {
            "model": config.model,
            "messages": messages,
            "stream": False,
        }
        if config.max_tokens is not None:
            params["max_tokens"] = config.max_tokens
        if config.temperature is not None:
            params["temperature"] = config.temperature
        if config.timeout is not None:
            params["timeout"] = config.timeout
        params.update(config.extra_params)
        return params

    def _call_chat(self, params: dict[str, Any]) -> Any:
        return self._client.chat.completions.create(**params)

    def _extract_content(self, response: Any) -> tuple[str, str | None]:
        msg = response.choices[0].message
        content = msg.content or ""
        reasoning = getattr(msg, "reasoning_content", None)
        return content, reasoning

    def _build_metadata(self, response: Any) -> dict[str, Any]:
        meta: dict[str, Any] = {}
        if hasattr(response, "usage") and response.usage:
            meta["usage"] = response.usage.model_dump()
        if hasattr(response, "model"):
            meta["model"] = response.model
        return meta

    def chat(self, request: AIRequest, config: ModelConfig) -> AIResponse:
        try:
            params = self._build_params(request, config)
            response = self._call_chat(params)
        except Exception as exc:
            _map_openai_exception(exc, model_name=config.model)

        content, reasoning = self._extract_content(response)
        return AIResponse(
            content=content,
            reasoning_content=reasoning,
            metadata=self._build_metadata(response),
        )


# ------------------------------------------------------------------------------
# Embedding Adapter
# ------------------------------------------------------------------------------


class EmbeddingAdapter(ABC):
    """Abstract base for text-embedding adapters."""

    @abstractmethod
    def embed(self, texts: list[str], config: ModelConfig) -> AIResponse:
        ...


class OpenAIEmbeddingAdapter(EmbeddingAdapter):
    """OpenAI-compatible embedding adapter."""

    DEFAULT_BASE_URL: str = ""
    ENV_KEY_NAMES: tuple[str, ...] = ()

    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ImportError("The 'openai' package is required.") from exc

        key = api_key or self._resolve_env_key()
        if not key:
            raise ConfigError(
                f"API key required for {self.__class__.__name__}. "
                f"Set one of: {self.ENV_KEY_NAMES}"
            )
        url = base_url or self.DEFAULT_BASE_URL or None
        self._client = OpenAI(api_key=key, base_url=url)

    def _resolve_env_key(self) -> str | None:
        for name in self.ENV_KEY_NAMES:
            key = os.environ.get(name)
            if key:
                return key
        return None

    def embed(self, texts: list[str], config: ModelConfig) -> AIResponse:
        params: dict[str, Any] = {
            "model": config.model,
            "input": texts,
        }
        if config.dimensions:
            params["dimensions"] = config.dimensions
        params.update(config.extra_params)

        try:
            resp = self._client.embeddings.create(**params)
        except Exception as exc:
            _map_openai_exception(exc, model_name=config.model)

        embedding = resp.data[0].embedding if resp.data else []
        meta = {}
        if hasattr(resp, "usage") and resp.usage:
            meta["usage"] = resp.usage.model_dump()
        return AIResponse(embedding=embedding, metadata=meta)


# ------------------------------------------------------------------------------
# Image Generation Adapter
# ------------------------------------------------------------------------------


class ImageGenAdapter(ABC):
    """Abstract base for image-generation adapters."""

    @abstractmethod
    def generate(self, prompt: str, config: ModelConfig) -> AIResponse:
        ...


class OpenAIImageGenAdapter(ImageGenAdapter):
    """OpenAI images.generations compatible adapter."""

    DEFAULT_BASE_URL: str = ""
    ENV_KEY_NAMES: tuple[str, ...] = ()

    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ImportError("The 'openai' package is required.") from exc

        key = api_key or self._resolve_env_key()
        if not key:
            raise ConfigError(
                f"API key required for {self.__class__.__name__}. "
                f"Set one of: {self.ENV_KEY_NAMES}"
            )
        url = base_url or self.DEFAULT_BASE_URL or None
        self._client = OpenAI(api_key=key, base_url=url)

    def _resolve_env_key(self) -> str | None:
        for name in self.ENV_KEY_NAMES:
            key = os.environ.get(name)
            if key:
                return key
        return None

    def generate(self, prompt: str, config: ModelConfig) -> AIResponse:
        params: dict[str, Any] = {
            "model": config.model,
            "prompt": prompt,
            "response_format": "b64_json",
        }
        params.update(config.extra_params)

        try:
            resp = self._client.images.generate(**params)
        except Exception as exc:
            _map_openai_exception(exc, model_name=config.model)

        images = []
        for d in resp.data:
            images.append(d.b64_json or d.url or "")
        meta = {}
        if hasattr(resp, "usage") and resp.usage:
            meta["usage"] = resp.usage.model_dump()
        return AIResponse(images=images, metadata=meta)
