"""Configuration error types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ConfigError(Exception):
    """Error raised when configuration cannot be loaded or converted."""

    message: str
    key: str = ""
    source: str = ""
    value: object = None
    expected: str = ""

    def __str__(self) -> str:
        parts = [self.message]
        if self.key:
            parts.append(f"key={self.key}")
        if self.source:
            parts.append(f"source={self.source}")
        if self.expected:
            parts.append(f"expected={self.expected}")
        if self.value is not None:
            parts.append(f"value={self.value!r}")
        return " | ".join(parts)

