"""Event-loop-owned generation leases; waiting never blocks a thread."""

from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from types import TracebackType
from uuid import uuid4

from .activity import RuntimeActivationState, RuntimeActivity


class RuntimeGenerationError(Exception):
    """Invalid generation lifecycle operation."""


@dataclass(frozen=True)
class RuntimeGenerationSnapshot[T]:
    generation: T
    generation_id: str
    activity: RuntimeActivity
    activation: RuntimeActivationState


class RuntimeGenerationLease[T](AbstractAsyncContextManager[T]):
    def __init__(self, handle: RuntimeHandle[T]) -> None:
        self._handle = handle

    async def __aenter__(self) -> T:
        return await self._handle._acquire_reader()

    async def __aexit__(self, exception_type: type[BaseException] | None,
                        exception: BaseException | None, traceback: TracebackType | None) -> None:
        self._handle._readers -= 1
        self._handle._changed.set()


class RuntimeWriteLease[T](AbstractAsyncContextManager[None]):
    def __init__(self, handle: RuntimeHandle[T]) -> None:
        self._handle = handle

    async def __aenter__(self) -> None:
        await self._handle._acquire_writer()

    async def __aexit__(self, exception_type: type[BaseException] | None,
                        exception: BaseException | None, traceback: TracebackType | None) -> None:
        self._handle._writer = False
        self._handle._changed.set()


class RuntimeActivityLease[T](AbstractAsyncContextManager[None]):
    def __init__(self, handle: RuntimeHandle[T], activity: RuntimeActivity) -> None:
        self._handle = handle
        self._activity = activity

    async def __aenter__(self) -> None:
        await self._handle._acquire_activity(self._activity)

    async def __aexit__(self, exception_type: type[BaseException] | None,
                        exception: BaseException | None, traceback: TracebackType | None) -> None:
        self._handle.set_activity(RuntimeActivity.IDLE)


class RuntimeHandle[T]:
    """One generation, with asynchronous use and exclusive activation scopes.

    All transitions occur on the Agent loop. Threads may consume immutable
    snapshots, but must not acquire leases or mutate lifecycle state.
    """

    def __init__(self, generation: T, *, generation_id: str = "") -> None:
        self._generation = generation
        self._generation_id = generation_id or f"generation_{uuid4().hex}"
        self._activity = RuntimeActivity.IDLE
        self._activation = RuntimeActivationState.ACTIVE
        self._readers = 0
        self._writer = False
        self._writers_waiting = 0
        self._changed = asyncio.Event()
        self._closed = False

    def read(self) -> RuntimeGenerationLease[T]:
        return RuntimeGenerationLease(self)

    def write(self) -> RuntimeWriteLease[T]:
        return RuntimeWriteLease(self)

    def activity_lease(self, activity: RuntimeActivity) -> RuntimeActivityLease[T]:
        if not isinstance(activity, RuntimeActivity) or activity in {RuntimeActivity.IDLE, RuntimeActivity.CONFIG_ACTIVATION}:
            raise RuntimeGenerationError("Runtime activity lease kind is invalid")
        return RuntimeActivityLease(self, activity)

    def snapshot(self) -> RuntimeGenerationSnapshot[T]:
        return RuntimeGenerationSnapshot(self._generation, self._generation_id, self._activity, self._activation)

    @property
    def activity(self) -> RuntimeActivity:
        return self._activity

    @property
    def generation_id(self) -> str:
        return self._generation_id

    @property
    def closed(self) -> bool:
        return self._closed

    def set_activity(self, activity: RuntimeActivity) -> None:
        if not isinstance(activity, RuntimeActivity):
            raise RuntimeGenerationError("Runtime activity is invalid")
        if activity is not RuntimeActivity.IDLE and self._activity is not RuntimeActivity.IDLE:
            raise RuntimeGenerationError("Runtime activity is already active")
        self._activity = activity
        self._changed.set()

    def begin_activation(self) -> None:
        self._require_open()
        if self._activity is not RuntimeActivity.IDLE or self._readers or self._writer:
            raise RuntimeGenerationError("Runtime generation activation requires an idle runtime")
        self._activation = RuntimeActivationState.PREPARING
        self._activity = RuntimeActivity.CONFIG_ACTIVATION

    def activate(self, generation: T, *, generation_id: str = "") -> str:
        self._require_open()
        if not self._writer or self._readers:
            raise RuntimeGenerationError("Runtime generation requires an exclusive write lease")
        if self._activity not in {RuntimeActivity.IDLE, RuntimeActivity.CONFIG_ACTIVATION}:
            raise RuntimeGenerationError("Runtime generation activation requires idle")
        self._generation = generation
        self._generation_id = generation_id or f"generation_{uuid4().hex}"
        self._activation = RuntimeActivationState.ACTIVE
        self._activity = RuntimeActivity.IDLE
        self._changed.set()
        return self._generation_id

    def fail_activation(self) -> None:
        self._activation = RuntimeActivationState.FAILED
        self._activity = RuntimeActivity.IDLE
        self._changed.set()

    async def close(self) -> None:
        self._closed = True
        self._changed.set()
        while self._readers or self._writer:
            self._changed.clear()
            await self._changed.wait()

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeGenerationError("Runtime generation is closed")

    async def _acquire_reader(self) -> T:
        while True:
            self._require_open()
            if not self._writer and not self._writers_waiting and self._activity is not RuntimeActivity.CONFIG_ACTIVATION:
                self._readers += 1
                return self._generation
            self._changed.clear()
            await self._changed.wait()

    async def _acquire_writer(self) -> None:
        self._writers_waiting += 1
        try:
            while True:
                self._require_open()
                if not self._writer and not self._readers:
                    self._writer = True
                    return
                self._changed.clear()
                await self._changed.wait()
        finally:
            self._writers_waiting -= 1
            self._changed.set()

    async def _acquire_activity(self, activity: RuntimeActivity) -> None:
        while True:
            self._require_open()
            if self._activity is not RuntimeActivity.CONFIG_ACTIVATION:
                self.set_activity(activity)
                return
            self._changed.clear()
            await self._changed.wait()
