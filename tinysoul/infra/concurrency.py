"""Reentrant reader-writer lock for shared-read, exclusive-write owners."""

from __future__ import annotations

from threading import Condition, get_ident
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
