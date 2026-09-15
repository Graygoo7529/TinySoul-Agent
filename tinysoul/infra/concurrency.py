"""Explicit concurrency boundaries for local operations, resources and queues."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar
from threading import Condition, Lock, get_ident
from types import TracebackType


class ConcurrencyContractError(Exception):
    """A lock was released without a matching acquisition."""


class ReadWriteLock:
    """Shared readers with one exclusive, reentrant writer.

    Semantics:

    - Any number of threads may hold the read side concurrently.
    - The write side is exclusive against readers and other writers.
    - A thread holding the write side may re-enter both sides.
    - A thread holding the read side may re-enter the read side.

    There is no writer-preference queue: the intended owner runs writers
    serially from one dispatcher, so writer starvation is not a concern.
    """

    def __init__(self) -> None:
        self._condition = Condition()
        self._readers: dict[int, int] = {}
        self._writer: int | None = None
        self._writer_depth = 0

    def read_locked(self) -> "_ReadSide":
        return _ReadSide(self)

    def write_locked(self) -> "_WriteSide":
        return _WriteSide(self)

    def acquire_read(self) -> None:
        me = get_ident()
        with self._condition:
            while not (
                self._writer is None
                or self._writer == me
                or me in self._readers
            ):
                self._condition.wait()
            self._readers[me] = self._readers.get(me, 0) + 1

    def release_read(self) -> None:
        me = get_ident()
        with self._condition:
            depth = self._readers.get(me, 0)
            if depth <= 0:
                raise ConcurrencyContractError(
                    "release_read without a matching acquire_read"
                )
            if depth == 1:
                del self._readers[me]
            else:
                self._readers[me] = depth - 1
            self._condition.notify_all()

    def acquire_write(self) -> None:
        me = get_ident()
        with self._condition:
            while not (
                self._writer == me
                or (
                    self._writer is None
                    and all(reader == me for reader in self._readers)
                )
            ):
                self._condition.wait()
            self._writer = me
            self._writer_depth += 1

    def release_write(self) -> None:
        me = get_ident()
        with self._condition:
            if self._writer != me or self._writer_depth <= 0:
                raise ConcurrencyContractError(
                    "release_write without a matching acquire_write"
                )
            self._writer_depth -= 1
            if self._writer_depth == 0:
                self._writer = None
            self._condition.notify_all()


class _ReadSide:
    def __init__(self, lock: ReadWriteLock) -> None:
        self._lock = lock

    def __enter__(self) -> None:
        self._lock.acquire_read()

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._lock.release_read()


class _WriteSide:
    def __init__(self, lock: ReadWriteLock) -> None:
        self._lock = lock

    def __enter__(self) -> None:
        self._lock.acquire_write()

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._lock.release_write()


T = TypeVar("T")


class JoinedOperations:
    """Defer cancellation until the caller has recorded a completed owner result.

    This boundary is for bounded local I/O. Network calls and arbitrary programs
    must supply their own cancellable async or process implementation.
    """

    def __init__(self) -> None:
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    async def run(self, operation: Callable[[], T]) -> T:
        if self._cancelled:
            raise asyncio.CancelledError
        worker = asyncio.create_task(asyncio.to_thread(operation))
        while True:
            try:
                return await asyncio.shield(worker)
            except asyncio.CancelledError:
                self._cancelled = True
                if worker.done():
                    return worker.result()

    def check_cancelled(self) -> None:
        """Called only after the completed result has reached its fact owner."""
        if self._cancelled:
            raise asyncio.CancelledError


@dataclass(frozen=True)
class CleanupDiagnostic:
    """Bounded cleanup evidence; never include exception text or resource data."""

    resource: str
    error_type: str

    def __post_init__(self) -> None:
        if not self.resource or not self.error_type:
            raise ConcurrencyContractError("Cleanup diagnostic identity is required")


type AsyncCloser = Callable[[], Awaitable[tuple[CleanupDiagnostic, ...] | None]]


class AsyncResourceScope:
    """Own asynchronous resources and join reverse-order cleanup exactly once.

    Cancellation of a caller never abandons cleanup. Concurrent close callers
    join the same task; callback failures remain diagnostics, not a replacement
    for an execution or commit failure. Nested scopes retain their diagnostics.
    """

    def __init__(self) -> None:
        self._callbacks: dict[str, AsyncCloser] = {}
        self._closing: asyncio.Task[tuple[CleanupDiagnostic, ...]] | None = None
        self._diagnostics: tuple[CleanupDiagnostic, ...] = ()

    @property
    def diagnostics(self) -> tuple[CleanupDiagnostic, ...]:
        return self._diagnostics

    def register(self, resource: str, close: AsyncCloser) -> None:
        if not resource or resource in self._callbacks or self._closing is not None:
            raise ConcurrencyContractError("Resource registration is invalid")
        self._callbacks[resource] = close

    async def close(self) -> tuple[CleanupDiagnostic, ...]:
        if self._closing is None:
            self._closing = asyncio.create_task(self._close_all())
        cancelled = False
        while not self._closing.done():
            try:
                await asyncio.shield(self._closing)
            except asyncio.CancelledError:
                cancelled = True
        result = self._closing.result()
        if cancelled:
            raise asyncio.CancelledError
        return result

    async def _close_all(self) -> tuple[CleanupDiagnostic, ...]:
        diagnostics: list[CleanupDiagnostic] = []
        for resource, callback in reversed(tuple(self._callbacks.items())):
            try:
                nested = await callback()
                if nested:
                    diagnostics.extend(nested)
            except (Exception, asyncio.CancelledError) as exc:
                diagnostics.append(CleanupDiagnostic(resource, type(exc).__name__))
        self._diagnostics = tuple(diagnostics)
        return self._diagnostics


class AsyncMailbox[T]:
    """Thread-safe producers, one event-loop consumer, no blocked reader thread."""

    def __init__(self) -> None:
        self._items: deque[T] = deque()
        self._lock = Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = asyncio.Event()

    def put(self, item: T) -> None:
        with self._lock:
            if self._loop is not None and self._loop.is_closed():
                raise ConcurrencyContractError("Mailbox event loop is closed")
            self._items.append(item)
            if self._loop is not None:
                self._loop.call_soon_threadsafe(self._ready.set)

    def get_nowait(self) -> T:
        with self._lock:
            if not self._items:
                raise asyncio.QueueEmpty
            return self._items.popleft()

    async def get(self) -> T:
        loop = asyncio.get_running_loop()
        while True:
            with self._lock:
                if self._loop is not None and self._loop is not loop:
                    raise ConcurrencyContractError("Mailbox belongs to another event loop")
                self._loop = loop
                if self._items:
                    return self._items.popleft()
                self._ready.clear()
            await self._ready.wait()
