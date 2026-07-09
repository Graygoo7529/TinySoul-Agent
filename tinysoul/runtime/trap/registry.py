"""Trap handler registry."""

from __future__ import annotations

from ..errors import RuntimeContractError
from .handler import TrapHandler


class TrapHandlerRegistry:
    """Registry that resolves trap handlers by reason or namespace prefix."""

    def __init__(self) -> None:
        self._exact: dict[str, TrapHandler] = {}
        self._prefix: dict[str, TrapHandler] = {}

    def register(self, reason: str, handler: TrapHandler) -> None:
        reason = self._normalize_key(reason)
        if reason in self._exact:
            raise RuntimeContractError(f"Trap handler already registered: {reason}")
        self._exact[reason] = handler

    def register_prefix(self, prefix: str, handler: TrapHandler) -> None:
        prefix = self._normalize_key(prefix)
        if prefix in self._prefix:
            raise RuntimeContractError(
                f"Trap prefix handler already registered: {prefix}"
            )
        self._prefix[prefix] = handler

    def handler_for(self, reason: str) -> TrapHandler:
        reason = self._normalize_key(reason)
        handler = self._exact.get(reason)
        if handler is not None:
            return handler

        matched_prefix = self._match_prefix(reason)
        if matched_prefix is not None:
            return matched_prefix

        raise RuntimeContractError(f"Unknown trap reason: {reason}")

    def _match_prefix(self, reason: str) -> TrapHandler | None:
        matches = [
            (prefix, handler)
            for prefix, handler in self._prefix.items()
            if reason == prefix or reason.startswith(f"{prefix}.")
        ]
        if not matches:
            return None
        prefix, handler = max(matches, key=lambda item: len(item[0]))
        return handler

    @staticmethod
    def _normalize_key(value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise RuntimeContractError("Trap registry key must be non-empty")
        return normalized
