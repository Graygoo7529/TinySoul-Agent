"""Provider adapter registry."""

from __future__ import annotations

from tinysoul.llm.errors import LLMContractError, LLMInvariantError
from tinysoul.llm.adapter_types import AdapterKind

from .base import ProviderAdapter


class ProviderRegistry:
    """Registry of provider adapters."""

    def __init__(self, adapters: list[ProviderAdapter] | None = None) -> None:
        self._adapters: dict[tuple[str, AdapterKind], ProviderAdapter] = {}
        for adapter in adapters or []:
            self.register(adapter)

    def register(self, adapter: ProviderAdapter) -> None:
        key = (adapter.provider_id, adapter.adapter_kind)
        if key in self._adapters:
            raise LLMInvariantError(
                "Provider adapter already registered: "
                f"{adapter.provider_id}/{adapter.adapter_kind.value}"
            )
        self._adapters[key] = adapter

    def get(
        self,
        provider_id: str,
        adapter_kind: AdapterKind,
    ) -> ProviderAdapter:
        try:
            return self._adapters[(provider_id, adapter_kind)]
        except KeyError as exc:
            raise LLMContractError(
                f"Unknown provider adapter: {provider_id}/{adapter_kind.value}"
            ) from exc

    def has(self, provider_id: str, adapter_kind: AdapterKind) -> bool:
        return (provider_id, adapter_kind) in self._adapters

    async def close(self) -> None:
        """Close every adapter even when one client's cleanup fails."""
        failure: Exception | None = None
        for adapter in reversed(tuple(self._adapters.values())):
            try:
                await adapter.close()
            except Exception as exc:
                if failure is None:
                    failure = exc
        if failure is not None:
            raise LLMInvariantError("Provider client cleanup failed") from failure
