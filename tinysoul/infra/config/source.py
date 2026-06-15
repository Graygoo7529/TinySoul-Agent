"""Configuration source model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class ConfigSource:
    """A named configuration source with flattened dotted keys."""

    name: str
    values: Mapping[str, object]

    @classmethod
    def empty(cls, name: str) -> "ConfigSource":
        return cls(name=name, values={})

