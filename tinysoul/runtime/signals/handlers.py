"""Runtime signal handlers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from .base import Signal


class SignalHandler(Protocol):
    """Protocol for runtime signal handlers."""

    def handle(self, signal: Signal) -> None:
        """Handle a single signal."""
        ...


class SignalHandlerRegistry:
    """Registry resolving signal handlers by exact name or namespace prefix."""

    def __init__(self) -> None:
        self._exact: dict[str, SignalHandler] = {}
        self._prefix: dict[str, SignalHandler] = {}

    def register(self, name: str, handler: SignalHandler) -> None:
        name = self._normalize_key(name)
        if name in self._exact:
            raise ValueError(f"Signal handler already registered: {name}")
        self._exact[name] = handler

    def register_prefix(self, prefix: str, handler: SignalHandler) -> None:
        prefix = self._normalize_key(prefix)
        if prefix in self._prefix:
            raise ValueError(f"Signal prefix handler already registered: {prefix}")
        self._prefix[prefix] = handler

    def dispatch(self, signals: Iterable[Signal]) -> None:
        for signal in signals:
            self.handler_for(signal.name).handle(signal)

    def handler_for(self, name: str) -> SignalHandler:
        name = self._normalize_key(name)
        handler = self._exact.get(name)
        if handler is not None:
            return handler

        matched_prefix = self._match_prefix(name)
        if matched_prefix is not None:
            return matched_prefix

        raise LookupError(f"Unknown signal name: {name}")

    def _match_prefix(self, name: str) -> SignalHandler | None:
        matches = [
            (prefix, handler)
            for prefix, handler in self._prefix.items()
            if name == prefix or name.startswith(f"{prefix}.")
        ]
        if not matches:
            return None
        prefix, handler = max(matches, key=lambda item: len(item[0]))
        return handler

    @staticmethod
    def _normalize_key(value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Signal registry key must be non-empty")
        return normalized
