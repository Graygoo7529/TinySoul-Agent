"""Typed Context segment extension points and deterministic composition."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from tinysoul.infra.json import JsonObject, to_json_object
from .errors import ContextContractError


class ContextSegment(Protocol):
    """Owner of one semantic Context section."""

    name: str

    def prepare(self) -> JsonObject: ...

    def render(self, state: JsonObject) -> str: ...


@dataclass(frozen=True)
class SegmentRegistry:
    """Explicit registry rejecting duplicate or unnamed segment owners."""

    segments: tuple[ContextSegment, ...] = field(default_factory=tuple)

    def register(self, segment: ContextSegment) -> "SegmentRegistry":
        name = getattr(segment, "name", "")
        if not isinstance(name, str) or not name:
            raise ContextContractError("Context segment name must be non-empty")
        if any(item.name == name for item in self.segments):
            raise ContextContractError(f"Context segment already registered: {name}")
        return SegmentRegistry((*self.segments, segment))

    def prepare(self) -> JsonObject:
        result: dict[str, object] = {}
        for segment in self.segments:
            result[segment.name] = segment.prepare()
        return to_json_object(result)

    def render(self, prepared: JsonObject) -> tuple[str, ...]:
        return tuple(
            segment.render(to_json_object(prepared.get(segment.name, {})))
            for segment in self.segments
        )
