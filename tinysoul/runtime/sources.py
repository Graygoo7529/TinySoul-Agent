"""Explicit asynchronous event sources and their observable lifecycle."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from pathlib import Path

from .events import EnvironmentEvent, EventReceipt, EventProtocolError

type EventSink = Callable[[EnvironmentEvent], Awaitable[EventReceipt]]


class SourceState(StrEnum):
    STOPPED = "stopped"
    RUNNING = "running"
    FAILED = "failed"
    DISABLED = "disabled"


@dataclass(frozen=True)
class SourceStatus:
    source: str
    state: SourceState
    error_type: str | None = None
    topics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source, str)
            or not self.source
            or not isinstance(self.state, SourceState)
        ):
            raise EventProtocolError("Source status requires a source identity and typed state")
        if any(not isinstance(topic, str) or not topic for topic in self.topics):
            raise EventProtocolError("Source topics must be non-empty text")
        object.__setattr__(self, "topics", tuple(self.topics))


class RuntimeSource(Protocol):
    @property
    def status(self) -> SourceStatus: ...

    async def start(self, publish: EventSink) -> None: ...

    async def stop(self) -> None: ...


@runtime_checkable
class RuntimeTimer(Protocol):
    async def start(self, tick: Callable[[], Awaitable[float]]) -> None: ...
    async def stop(self) -> None: ...


@runtime_checkable
class RuntimeWatcher(Protocol):
    async def start(self, root: Path, *, include: Callable[[Path], bool], changed: Callable[[], Awaitable[None]], failed: Callable[[str], Awaitable[None]], debounce_ms: int) -> None: ...
    async def stop(self) -> None: ...
