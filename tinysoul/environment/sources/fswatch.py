"""One joined native file watcher; changes are hints, not filesystem facts."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

from watchfiles import awatch

from ..errors import EnvironmentError


class FileWatcher:
    def __init__(self) -> None:
        self._stop = asyncio.Event()
        self._ready = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._error: Exception | None = None

    async def start(
        self,
        root: Path,
        *,
        include: Callable[[Path], bool],
        changed: Callable[[], Awaitable[None]],
        failed: Callable[[str], Awaitable[None]],
        debounce_ms: int,
    ) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._ready.clear()
        self._error = None

        async def serve() -> None:
            try:
                stream = awatch(
                    root,
                    watch_filter=lambda _kind, path: include(Path(path)),
                    debounce=debounce_ms,
                    step=min(50, debounce_ms),
                    stop_event=self._stop,
                    rust_timeout=100,
                    yield_on_timeout=True,
                )
                try:
                    while not self._stop.is_set():
                        try:
                            changes = await anext(stream)
                        except StopAsyncIteration:
                            break
                        except Exception as exc:
                            self._error = exc
                            if self._ready.is_set():
                                await failed(type(exc).__name__)
                            break
                        self._ready.set()
                        if changes and not self._stop.is_set():
                            await changed()
                finally:
                    await stream.aclose()
            finally:
                self._ready.set()

        self._task = asyncio.create_task(serve(), name="tinysoul-file-watch")
        await self._ready.wait()
        if self._task.done():
            self._task.result()  # Owner/callback failures keep their own semantics.
        if self._error is not None:
            await self.stop()
            raise EnvironmentError("File watcher could not start") from self._error

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            task, self._task = self._task, None
            await task
