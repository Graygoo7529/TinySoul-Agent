"""Explicit Turn segment registration, rendering and prepared updates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
import re
from typing import Protocol, runtime_checkable

from tinysoul.infra.json import JsonObject
from tinysoul.llm.protocol.messages import Message

from ..errors import ContextContractError, ContextInvariantError
from ..providers import SegmentSelectionView


class SegmentSlot(StrEnum):
    BACKGROUND = "background"
    TRACE = "trace"
    WORKING = "working"


class SegmentShape(StrEnum):
    STATE = "state"
    HEAP = "heap"
    STACK = "stack"
    MAP = "map"


class SegmentCapability(StrEnum):
    INSPECT = "inspect"
    SELECT = "select"
    RECLAIM = "reclaim"


@dataclass(frozen=True)
class SegmentDescriptor:
    id: str
    owner: str
    slot: SegmentSlot
    order: int
    ref_prefixes: tuple[str, ...] = ()
    shape: SegmentShape = SegmentShape.STATE
    capabilities: frozenset[SegmentCapability] = frozenset()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.id, str)
            or re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", self.id) is None
        ):
            raise ContextContractError("Segment id must use lower_snake_case")
        if not isinstance(self.owner, str) or not self.owner:
            raise ContextContractError("Segment owner must be non-empty")
        if not isinstance(self.slot, SegmentSlot):
            raise ContextContractError("Segment slot must be a SegmentSlot")
        if isinstance(self.order, bool) or not isinstance(self.order, int):
            raise ContextContractError("Segment order must be an integer")
        prefixes = tuple(self.ref_prefixes)
        if any(not isinstance(prefix, str) or not prefix for prefix in prefixes):
            raise ContextContractError(
                "Segment reference routes must be non-empty text"
            )
        object.__setattr__(self, "ref_prefixes", prefixes)
        if not isinstance(self.shape, SegmentShape):
            raise ContextContractError("Segment shape must be a SegmentShape")
        capabilities = frozenset(self.capabilities)
        if any(not isinstance(item, SegmentCapability) for item in capabilities):
            raise ContextContractError("Segment capabilities must be typed")
        if bool(prefixes) != (SegmentCapability.INSPECT in capabilities):
            raise ContextContractError(
                "Inspection capability requires explicit reference routes"
            )
        object.__setattr__(self, "capabilities", capabilities)

    @property
    def sort_key(self) -> tuple[int, int, str]:
        return tuple(SegmentSlot).index(self.slot), self.order, self.id


@dataclass(frozen=True)
class TurnInfo:
    turn_id: str
    day: date

    def __post_init__(self) -> None:
        if not isinstance(self.turn_id, str) or not self.turn_id:
            raise ContextContractError("Segment Turn identity must be non-empty")
        if not isinstance(self.day, date):
            raise ContextContractError("Segment Turn day must be a date")


@dataclass(frozen=True)
class SegmentProjection:
    descriptor: SegmentDescriptor
    messages: tuple[Message, ...]


class ContextSegment(Protocol):
    """One Turn's view; render and seal perform no I/O."""

    def render(self) -> tuple[Message, ...]: ...

    def seal(self) -> JsonObject: ...

    async def close(self) -> None: ...


class UpdatingSegment[U, P](ContextSegment, Protocol):
    async def prepare(self, updates: tuple[U, ...]) -> P: ...

    def install(self, prepared: P) -> None: ...


class SegmentProvider[S: ContextSegment](Protocol):
    async def open(self, info: TurnInfo) -> S: ...


@runtime_checkable
class InspectableSegment(Protocol):
    async def inspect(
        self, ref: str, *, continuation: str | None = None
    ) -> JsonObject: ...


@runtime_checkable
class SelectableSegment(Protocol):
    def selection_view(self) -> SegmentSelectionView: ...


@dataclass(frozen=True)
class SegmentReclaim:
    reclaimed_chars: int = 0
    evicted_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            isinstance(self.reclaimed_chars, bool)
            or not isinstance(self.reclaimed_chars, int)
            or self.reclaimed_chars < 0
        ):
            raise ContextInvariantError(
                "Segment reclamation must report non-negative characters"
            )
        refs = tuple(self.evicted_refs)
        if any(not isinstance(ref, str) or not ref for ref in refs):
            raise ContextInvariantError("Reclaimed references must be non-empty text")
        object.__setattr__(self, "evicted_refs", refs)


@runtime_checkable
class ReclaimableSegment(Protocol):
    def reclaim(self, required_chars: int) -> SegmentReclaim: ...
