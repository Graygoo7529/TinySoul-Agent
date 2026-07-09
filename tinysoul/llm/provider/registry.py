"""Provider adapter registry."""

from __future__ import annotations

from tinysoul.llm.errors import LLMContractError, LLMInvariantError

from .base import ProviderAdapter


class ProviderRegistry:
    """Registry of provider adapters."""

    def __init__(self, adapters: list[ProviderAdapter] | None = None) -> None:
        self._adapters: dict[str, ProviderAdapter] = {}
        for adapter in adapters or []:
            self.register(adapter)

    def register(self, adapter: ProviderAdapter) -> None:
        if adapter.provider_id in self._adapters:
            raise LLMInvariantError(
                f"Provider already registered: {adapter.provider_id}"
            )
        self._adapters[adapter.provider_id] = adapter

    def get(self, provider_id: str) -> ProviderAdapter:
        try:
            return self._adapters[provider_id]
        except KeyError as exc:
            raise LLMContractError(f"Unknown provider: {provider_id}") from exc
