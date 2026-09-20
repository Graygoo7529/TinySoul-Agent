"""Joined asynchronous timer I/O; the injected policy owns due work."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable


class DeadlineTimer:
    """Wait for the next policy deadline, with explicit stop and no busy loop."""

    def __init__(self) -> None:
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self, tick: Callable[[], Awaitable[float]]) -> None:
        if self._task is not None:
            return
        self._stop.clear()

        async def serve() -> None:
            while not self._stop.is_set():
                delay = await tick()
                try:
                    await asyncio.wait_for(self._stop.wait(), delay)
                except TimeoutError:
                    pass

        self._task = asyncio.create_task(serve(), name="tinysoul-deadline-timer")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            task, self._task = self._task, None
            await task
