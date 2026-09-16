"""Uvicorn transport sharing the application's event loop and lifecycle."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
import socket

import uvicorn

from ..config import EndpointSettings
from ..engine import EndpointEngine
from ..errors import EndpointServerError
from .app import create_endpoint_app


class _EmbeddedServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self) -> Iterator[None]:
        # The embedding process owns Ctrl-C and shutdown policy.
        yield


class EndpointASGIServer:
    """Serve on a pre-bound loopback socket without a second event loop."""

    def __init__(self, *, engine: EndpointEngine, settings: EndpointSettings) -> None:
        self._settings = settings
        self._app = create_endpoint_app(engine, settings)
        self._socket: socket.socket | None = None
        self._server: uvicorn.Server | None = None
        self._task: asyncio.Task[None] | None = None
        self._port = 0

    @property
    def port(self) -> int:
        if self._port <= 0:
            raise EndpointServerError("Endpoint server has no bound port")
        return self._port

    async def start(self) -> None:
        if self._task is not None:
            raise EndpointServerError("Endpoint ASGI server is already started")
        family = socket.AF_INET6 if ":" in self._settings.host else socket.AF_INET
        bound = socket.socket(family, socket.SOCK_STREAM)
        try:
            bound.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            bound.bind((self._settings.host, self._settings.port))
            bound.listen(2048)
            bound.setblocking(False)
        except OSError as exc:
            bound.close()
            raise EndpointServerError("Endpoint socket could not be bound") from exc
        self._port = int(bound.getsockname()[1])
        self._socket = bound
        server = _EmbeddedServer(uvicorn.Config(
            self._app,
            host=self._settings.host,
            port=self._port,
            log_level="warning",
            access_log=False,
            timeout_graceful_shutdown=5,
        ))
        self._server = server
        self._task = asyncio.create_task(server.serve(sockets=[bound]))
        try:
            async with asyncio.timeout(10):
                while not server.started:
                    if self._task.done():
                        await self._task
                        raise EndpointServerError("Endpoint ASGI server did not start")
                    await asyncio.sleep(0.01)
        except BaseException as exc:
            try:
                await self.stop()
            except (Exception, asyncio.CancelledError):
                pass
            if isinstance(exc, TimeoutError):
                raise EndpointServerError("Endpoint ASGI startup timed out") from exc
            raise

    async def stop(self) -> None:
        server, task, bound = self._server, self._task, self._socket
        if server is None or task is None:
            return
        server.should_exit = True
        if not server.started and not task.done():
            task.cancel()
        cancelled = False
        try:
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    caller = asyncio.current_task()
                    if caller is not None and caller.cancelling():
                        cancelled = True
            if not task.cancelled():
                task.result()
        except Exception as exc:
            raise EndpointServerError("Endpoint ASGI server failed") from exc
        finally:
            if bound is not None:
                bound.close()
            self._socket = None
            self._server = None
            self._task = None
        if cancelled:
            raise asyncio.CancelledError
