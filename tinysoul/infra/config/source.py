"""Configuration source model."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ConfigSource:
    """A named configuration source with flattened dotted keys."""

    name: str
    values: Mapping[str, object]

    @classmethod
    def empty(cls, name: str) -> "ConfigSource":
        return cls(name=name, values={})
