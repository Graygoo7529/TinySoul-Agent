"""AI client for TinySoul.

Provides unified interface for Chat, Embedding, and Image Generation.
Supports multi-model pools with internal retry and per-pool failover.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import replace
from typing import Any, Mapping

from tinysoul.infra.config import defaults, settings
from tinysoul.trap import AbortError, ConfigError, LLMTransientError, SystemExhaustedError
from tinysoul.infra import EventLogger, NullSink

from .adapters import create_adapter
from .config import (
    ChatConfig,
    ChatProfile,
    EmbedConfig,
    ImageConfig,
    LLMProfileName,
    ModelCapability,
    ModelConfig,
    ModelType,
    build_chat_profiles,
    normalize_profile_name,
)
from .request import AIRequest
from .resolver import merge_config, resolve_defaults
from .response import AIResponse


class _AIClientSingleton:
    """Singleton manager for AIClient."""

    _instance: AIClient | None = None

    @classmethod
    def get_instance(cls) -> AIClient:
        if cls._instance is None:
            configs = cls._auto_detect_configs()
            if not configs:
                raise ConfigError(
                    "No AI API key found. Please set one of: "
                    "GLM_API_KEY, ZHIPU_API_KEY, KIMI_API_KEY, MOONSHOT_API_KEY, "
                    "DEEPSEEK_API_KEY, MINIMAX_API_KEY "
                    "in environment or .env file"
                )
            cls._instance = AIClient(configs)
        return cls._instance

    @classmethod
    def _auto_detect_configs(cls) -> list[ModelConfig]:
        configs: list[ModelConfig] = []
        for provider, model_specs in defaults.DEFAULT_PROVIDER_MODEL_SPECS.items():
            for meta in model_specs.values():
                api_key = next(
                    (
                        os.environ.get(k)
                        for k in meta["api_key_envs"]
                        if os.environ.get(k)
                    ),
                    None,
                )
                if not api_key:
                    continue
                model = os.environ.get(meta["model_env"])
                if not model:
                    model = meta.get("default_model")
                if not model:
                    continue

                model_type = ModelType(meta["model_type"])
                caps = [ModelCapability(c) for c in meta.get("capabilities", ["text"])]

                # Inject per-provider default params from settings
                default_params = defaults.DEFAULT_PROVIDER_PARAMS.get(provider, {})

                configs.append(
                    ModelConfig(
                        provider=provider,
                        model=model,
                        model_type=model_type,
                        capabilities=caps,
                        api_key=api_key,
                        **default_params,
                    )
                )
        return configs

    @classmethod
    def reset_instance(cls) -> None:
        cls._instance = None


class AIClient:
    """Multi-model AI client with per-pool retry and failover."""

    def __init__(
        self,
        configs: list[ModelConfig],
        logger: EventLogger | None = None,
        chat_profiles: Mapping[str | LLMProfileName, ChatProfile | Mapping[str, Any]] | None = None,
    ) -> None:
        if not configs:
            raise ConfigError("At least one ModelConfig is required")

        chat_configs = [c for c in configs if c.model_type == ModelType.CHAT]
        self._chat_configs_by_provider: dict[str, list[ModelConfig]] = {}
        for config in chat_configs:
            self._chat_configs_by_provider.setdefault(config.provider, []).append(config)
        self._embed_pool = [c for c in configs if c.model_type == ModelType.EMBEDDING]
        self._image_gen_pool = [c for c in configs if c.model_type == ModelType.IMAGE_GEN]

        self._chat_profiles = build_chat_profiles(chat_profiles or settings.chat_profiles)
        self._chat_indices: dict[str, int] = {
            name: 0 for name in self._chat_profiles
        }
        self._chat_indices_lock = threading.Lock()
        self._embed_idx = 0
        self._image_gen_idx = 0
        self._embed_idx_lock = threading.Lock()
        self._image_gen_idx_lock = threading.Lock()

        self._adapters: dict[tuple[str, str, str | None, str | None], Any] = {}
        self._adapters_lock = threading.Lock()
        self._logger = logger or EventLogger(sinks=[NullSink()])
        self._ready_emitted = False

    def set_logger(self, logger: EventLogger) -> None:
        """Attach (or replace) the event logger."""
        self._logger = logger
        self._maybe_emit_ready()

    def _maybe_emit_ready(self) -> None:
        """Emit llm_ready once when a usable logger is present."""
        if self._ready_emitted:
            return
        for profile in self._chat_profiles:
            pool = self._build_chat_pool(profile)
            if not pool:
                continue
            self._logger.llm_ready(
                model=pool[0].model,
                provider=pool[0].provider,
                profile=profile,
            )
        self._ready_emitted = True

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    def current_chat_config(self, profile: LLMProfileName | str) -> ModelConfig:
        profile_name = normalize_profile_name(profile)
        pool = self._build_chat_pool(profile_name)
        if not pool:
            raise ConfigError(f"No chat models configured for profile '{profile_name}'")
        return pool[self._chat_indices.get(profile_name, 0)]

    def current_chat_model_name(self, profile: LLMProfileName | str) -> str:
        return self.current_chat_config(profile).model

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        profile: LLMProfileName | str,
        system: list[dict[str, str]] | None = None,
        config: ChatConfig | None = None,
    ) -> AIResponse:
        profile_name = normalize_profile_name(profile)
        pool = self._build_chat_pool(profile_name)
        if not pool:
            raise ConfigError(f"No chat models configured for profile '{profile_name}'")

        profile_config = self._chat_profiles[profile_name].config
        effective_override = merge_config(
            ModelConfig(provider="__profile__", model="__profile__"),
            profile_config,
        )
        effective_override = merge_config(effective_override, config)
        request_config = ChatConfig(
            temperature=effective_override.temperature,
            max_tokens=effective_override.max_tokens,
            enable_thinking=effective_override.enable_thinking,
            extra_params=effective_override.extra_params,
            timeout=effective_override.timeout,
        )
        request = AIRequest(messages=messages, system=system, config=request_config)
        with self._chat_indices_lock:
            start_idx = self._chat_indices.get(profile_name, 0)
            if start_idx >= len(pool):
                start_idx = 0

        response, final_idx = self._call_with_retry(
            pool=pool,
            start_idx=start_idx,
            call_fn=lambda adapter, cfg: adapter.chat(request, cfg),
            override_config=request_config,
            profile=profile_name,
        )
        with self._chat_indices_lock:
            self._chat_indices[profile_name] = final_idx
        return response

    def _build_chat_pool(self, profile: LLMProfileName | str) -> list[ModelConfig]:
        profile_name = normalize_profile_name(profile)
        if profile_name not in self._chat_profiles:
            raise ConfigError(f"Unknown chat profile '{profile_name}'")

        route = self._chat_profiles[profile_name]
        pool: list[ModelConfig] = []
        for provider in route.provider_chain:
            base = self._select_chat_config(provider, route)
            if base is None:
                continue
            override = route.chat_model_overrides.get(provider)
            if override is None:
                pool.append(base)
                continue
            capabilities = override.capabilities or base.capabilities
            pool.append(replace(base, model=override.model, capabilities=capabilities))
        return pool

    def _select_chat_config(
        self,
        provider: str,
        profile: ChatProfile,
    ) -> ModelConfig | None:
        candidates = self._chat_configs_by_provider.get(provider, [])
        if not candidates:
            return None

        override = profile.chat_model_overrides.get(provider)
        if override is not None:
            for candidate in candidates:
                if candidate.model == override.model:
                    return candidate
            if override.capabilities is None:
                raise ConfigError(
                    "Chat model override for provider "
                    f"'{provider}' references unknown model '{override.model}' "
                    "without explicit capabilities"
                )
            return candidates[0]

        required = set(profile.required_capabilities)
        eligible = [
            candidate
            for candidate in candidates
            if required.issubset(set(candidate.capabilities))
        ]
        if not eligible:
            return None

        preferred = set(profile.preferred_capabilities)
        if preferred:
            for candidate in eligible:
                if preferred.issubset(set(candidate.capabilities)):
                    return candidate
        return eligible[0]

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    def embed(
        self,
        texts: list[str],
        config: EmbedConfig | None = None,
    ) -> AIResponse:
        with self._embed_idx_lock:
            start_idx = self._embed_idx
            if start_idx >= len(self._embed_pool):
                start_idx = 0

        response, final_idx = self._call_with_retry(
            pool=self._embed_pool,
            start_idx=start_idx,
            call_fn=lambda adapter, cfg: adapter.embed(texts, cfg),
            override_config=config,
            profile="embedding",
        )
        with self._embed_idx_lock:
            self._embed_idx = final_idx
        return response

    # ------------------------------------------------------------------
    # Image Generation
    # ------------------------------------------------------------------

    def generate_image(
        self,
        prompt: str,
        config: ImageConfig | None = None,
    ) -> AIResponse:
        with self._image_gen_idx_lock:
            start_idx = self._image_gen_idx
            if start_idx >= len(self._image_gen_pool):
                start_idx = 0

        response, final_idx = self._call_with_retry(
            pool=self._image_gen_pool,
            start_idx=start_idx,
            call_fn=lambda adapter, cfg: adapter.generate(prompt, cfg),
            override_config=config,
            profile="image_gen",
        )
        with self._image_gen_idx_lock:
            self._image_gen_idx = final_idx
        return response

    # ------------------------------------------------------------------
    # Internal retry + failover
    # ------------------------------------------------------------------

    def _call_with_retry(
        self,
        pool: list[ModelConfig],
        start_idx: int,
        call_fn: Any,
        override_config: ChatConfig | EmbedConfig | ImageConfig | None = None,
        profile: str = "",
    ) -> tuple[AIResponse, int]:
        if not pool:
            raise ConfigError("No models configured for this task type")

        last_error: Exception | None = None
        tried_indices: set[int] = set()

        def _try_config(idx: int) -> AIResponse | None:
            nonlocal last_error
            pool_config = pool[idx]

            # 1. Merge request-level override
            effective_config = merge_config(pool_config, override_config)
            # 2. Resolve framework defaults for any remaining None values
            effective_config = resolve_defaults(effective_config)

            adapter = self._get_adapter(effective_config)
            # resolve_defaults guarantees these are non-None, but the type
            # checker doesn't know that — narrow explicitly.
            assert effective_config.max_retries is not None
            assert effective_config.base_retry_delay is not None
            for attempt in range(effective_config.max_retries):
                try:
                    return call_fn(adapter, effective_config)
                except AbortError:
                    raise  # Fatal errors (auth, config) should not be retried or failed-over
                except Exception as e:
                    last_error = e
                    if attempt < effective_config.max_retries - 1:
                        self._logger.llm_retry(
                            step="llm_call",
                            model=effective_config.model,
                            provider=effective_config.provider,
                            profile=profile,
                            attempt=attempt + 1,
                            max_attempts=effective_config.max_retries,
                        )
                        time.sleep(effective_config.base_retry_delay * (2**attempt))
            return None

        # 1. Try the current provider first.
        tried_indices.add(start_idx)
        result = _try_config(start_idx)
        if result is not None:
            return result, start_idx

        # 2. Current provider exhausted — reset to head and scan forward,
        #    skipping any already-tried indices (including start_idx).
        prev_idx = start_idx
        for candidate_idx in range(len(pool)):
            if candidate_idx in tried_indices:
                continue
            tried_indices.add(candidate_idx)
            self._logger.llm_failover(
                from_model=pool[prev_idx].model,
                to_model=pool[candidate_idx].model,
                from_provider=pool[prev_idx].provider,
                to_provider=pool[candidate_idx].provider,
                profile=profile,
            )
            prev_idx = candidate_idx
            result = _try_config(candidate_idx)
            if result is not None:
                return result, candidate_idx

        raise SystemExhaustedError(
            f"All models exhausted after retries. Last error: {last_error}"
        ) from last_error

    def _get_adapter(self, config: ModelConfig) -> Any:
        key = (
            config.provider,
            config.model_type.value,
            config.api_key,
            config.base_url,
        )
        with self._adapters_lock:
            if key not in self._adapters:
                self._adapters[key] = create_adapter(config)
            return self._adapters[key]


# ------------------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------------------


def get_ai_client() -> AIClient:
    return _AIClientSingleton.get_instance()


def reset_ai_client() -> None:
    _AIClientSingleton.reset_instance()
