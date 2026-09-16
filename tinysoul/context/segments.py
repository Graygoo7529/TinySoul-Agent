"""Explicit Turn segment registration, rendering and prepared updates."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
import re
from typing import Callable, Protocol

from tinysoul.infra.concurrency import AsyncResourceScope, CleanupDiagnostic
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.llm.messages import Message
from tinysoul.runtime import RunLevel, RuntimeException, RuntimeTransferInterrupt, Signal

from .errors import ContextContractError, ContextError, ContextInvariantError


class SegmentSlot(StrEnum):
    BACKGROUND = "background"
    TRACE = "trace"
    WORKING = "working"


@dataclass(frozen=True)
class SegmentDescriptor:
    id: str
    owner: str
    slot: SegmentSlot
    order: int

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


class _Installation(Protocol):
    def install(self) -> None: ...


@dataclass(frozen=True)
class _PreparedUpdate[U, P]:
    segment: UpdatingSegment[U, P]
    value: P

    def install(self) -> None:
        self.segment.install(self.value)


class _UpdatePort(Protocol):
    async def prepare(self, signals: tuple[Signal, ...]) -> _Installation: ...


@dataclass(frozen=True)
class _TypedUpdatePort[U, P]:
    segment: UpdatingSegment[U, P]
    decode: Callable[[Signal], U]
    update_type: type[U]

    async def prepare(self, signals: tuple[Signal, ...]) -> _Installation:
        try:
            updates = tuple(self.decode(signal) for signal in signals)
            if any(not isinstance(update, self.update_type) for update in updates):
                raise ContextContractError("Segment decoder returned an invalid update type")
            return _PreparedUpdate(self.segment, await self.segment.prepare(updates))
        except (ContextError, RuntimeException, RuntimeTransferInterrupt):
            raise
        except Exception as exc:
            raise ContextInvariantError("Segment update provider violated its contract") from exc


@dataclass(frozen=True)
class _OpenedSegment:
    descriptor: SegmentDescriptor
    segment: ContextSegment
    signal_name: str
    updates: _UpdatePort


class RegisteredSegment(Protocol):
    @property
    def descriptor(self) -> SegmentDescriptor: ...

    @property
    def signal_name(self) -> str: ...

    async def open(self, info: TurnInfo) -> _OpenedSegment: ...


@dataclass(frozen=True)
class SegmentRegistration[U, P]:
    """Bind an owner's codec and update types once at assembly."""

    descriptor: SegmentDescriptor
    provider: SegmentProvider[UpdatingSegment[U, P]]
    signal_name: str
    update_type: type[U]
    decode: Callable[[Signal], U]

    def __post_init__(self) -> None:
        if not self.signal_name.startswith("context."):
            raise ContextContractError("Segment update signals must use the Context namespace")

    async def open(self, info: TurnInfo) -> _OpenedSegment:
        try:
            segment = await self.provider.open(info)
        except (ContextError, RuntimeException, RuntimeTransferInterrupt):
            raise
        except Exception as exc:
            raise ContextInvariantError("Segment provider failed to open a view") from exc
        return _OpenedSegment(
            self.descriptor, segment, self.signal_name,
            _TypedUpdatePort(segment, self.decode, self.update_type),
        )


@dataclass(frozen=True)
class SegmentRegistry:
    registrations: tuple[RegisteredSegment, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "registrations", tuple(self.registrations))
        ids = tuple(item.descriptor.id for item in self.registrations)
        routes = tuple(item.signal_name for item in self.registrations)
        if len(set(ids)) != len(ids) or len(set(routes)) != len(routes):
            raise ContextContractError("Segment identities and update routes must be unique")

    def register(self, registration: RegisteredSegment) -> SegmentRegistry:
        return SegmentRegistry((*self.registrations, registration))

    def for_turn(self, info: TurnInfo) -> TurnSegments:
        return TurnSegments(info, self.registrations)


@dataclass(frozen=True)
class PreparedSegmentBatch:
    """Opaque candidate owned by the Turn which prepared it; installed once."""

    installations: tuple[_Installation, ...]


class TurnSegments:
    """Own opened views and install a batch only after every prepare succeeds."""

    def __init__(self, info: TurnInfo, registrations: tuple[RegisteredSegment, ...]) -> None:
        self._info = info
        self._registrations = registrations
        self._opened: list[_OpenedSegment] = []
        self._resources = AsyncResourceScope()
        self._opening = False
        self._ready = False
        self._closed = False
        self._install_failed = False
        self._preparing = False
        self._pending: PreparedSegmentBatch | None = None

    async def open(self) -> None:
        if self._opening or self._closed:
            raise ContextContractError("Turn segments can only be opened once")
        self._opening = True
        ordered = sorted(self._registrations, key=lambda item: item.descriptor.sort_key)
        try:
            for registration in ordered:
                opened = await registration.open(self._info)
                self._resources.register(opened.descriptor.id, opened.segment.close)
                self._opened.append(opened)
        except (Exception, asyncio.CancelledError):
            try:
                await self.close()
            except asyncio.CancelledError:
                # close joins all owners; preserve the original open failure.
                pass
            raise
        self._ready = True

    def accepts(self, signal: Signal) -> bool:
        return any(item.signal_name == signal.name for item in self._opened)

    async def prepare(self, signals: tuple[Signal, ...]) -> PreparedSegmentBatch:
        self._require_ready()
        if self._preparing:
            raise ContextContractError("Segment preparation is already in progress")
        if any(not self.accepts(signal) for signal in signals):
            raise ContextContractError("No registered segment consumes this update")
        for signal in signals:
            turn = signal.scope.nearest(RunLevel.TURN)
            if turn is None or turn.name != self._info.turn_id:
                raise ContextContractError("Segment update belongs to another Turn")
        self._pending = None
        self._preparing = True
        prepared: list[_Installation] = []
        try:
            for opened in self._opened:
                batch = tuple(signal for signal in signals if signal.name == opened.signal_name)
                if batch:
                    prepared.append(await opened.updates.prepare(batch))
            self._require_ready()
            self._pending = PreparedSegmentBatch(tuple(prepared))
            return self._pending
        finally:
            self._preparing = False

    def install(self, prepared: PreparedSegmentBatch) -> None:
        self._require_ready()
        if prepared is not self._pending or self._preparing:
            raise ContextContractError("Prepared segment batch is stale or belongs to another Turn")
        self._pending = None
        try:
            for item in prepared.installations:
                item.install()
        except (Exception, asyncio.CancelledError) as exc:
            self._install_failed = True
            raise ContextInvariantError("Context segment installation failed; batch cannot be replayed") from exc

    def render(self) -> tuple[SegmentProjection, ...]:
        self._require_ready()
        try:
            return tuple(
                SegmentProjection(item.descriptor, item.segment.render())
                for item in self._opened
            )
        except Exception as exc:
            raise ContextInvariantError("Segment could not render its installed view") from exc

    def seal(self) -> JsonObject:
        if self._closed:
            return {}
        try:
            return {
                item.descriptor.id: to_json_object(item.segment.seal())
                for item in self._opened
            }
        except Exception as exc:
            raise ContextInvariantError("Segment could not seal its installed view") from exc

    async def close(self) -> tuple[CleanupDiagnostic, ...]:
        self._closed = True
        return await self._resources.close()

    def _require_ready(self) -> None:
        if not self._ready or self._closed or self._install_failed:
            raise ContextContractError("Turn segments are not available for composition or updates")
