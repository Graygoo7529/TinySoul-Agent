"""Explicit Turn segment registration, rendering and prepared updates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from tinysoul.runtime import RuntimeException, RuntimeTransferInterrupt, Signal

from ..errors import ContextContractError, ContextError, ContextInvariantError


from .protocol import (
    ContextSegment,
    UpdatingSegment,
    SegmentProvider,
    SegmentDescriptor,
    TurnInfo,
)


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
                raise ContextContractError(
                    "Segment decoder returned an invalid update type"
                )
            return _PreparedUpdate(self.segment, await self.segment.prepare(updates))
        except (ContextError, RuntimeException, RuntimeTransferInterrupt):
            raise
        except Exception as exc:
            raise ContextInvariantError(
                "Segment update provider violated its contract"
            ) from exc


@dataclass(frozen=True)
class _OpenedSegment:
    descriptor: SegmentDescriptor
    segment: ContextSegment
    signal_name: str | None = None
    updates: _UpdatePort | None = None


class RegisteredSegment(Protocol):
    @property
    def descriptor(self) -> SegmentDescriptor: ...

    @property
    def signal_name(self) -> str | None: ...

    async def open(self, info: TurnInfo) -> _OpenedSegment: ...


@dataclass(frozen=True)
class ReadOnlySegmentRegistration:
    """Open a fixed Turn view without inventing an update channel."""

    descriptor: SegmentDescriptor
    provider: SegmentProvider[ContextSegment]
    signal_name: None = None

    async def open(self, info: TurnInfo) -> _OpenedSegment:
        try:
            return _OpenedSegment(self.descriptor, await self.provider.open(info))
        except (ContextError, RuntimeException, RuntimeTransferInterrupt):
            raise
        except Exception as exc:
            raise ContextInvariantError(
                "Segment provider failed to open a view"
            ) from exc


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
            raise ContextContractError(
                "Segment update signals must use the Context namespace"
            )

    async def open(self, info: TurnInfo) -> _OpenedSegment:
        try:
            segment = await self.provider.open(info)
        except (ContextError, RuntimeException, RuntimeTransferInterrupt):
            raise
        except Exception as exc:
            raise ContextInvariantError(
                "Segment provider failed to open a view"
            ) from exc
        return _OpenedSegment(
            self.descriptor,
            segment,
            self.signal_name,
            _TypedUpdatePort(segment, self.decode, self.update_type),
        )
