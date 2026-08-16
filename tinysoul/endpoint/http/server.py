"""Uvicorn lifecycle adapter for the Endpoint HTTP application."""

from __future__ import annotations

import socket
from threading import Thread
from time import monotonic, sleep

import uvicorn

from ..config import EndpointSettings
from ..engine import EndpointEngine
from ..errors import EndpointServerError
from .app import create_endpoint_app


class EndpointASGIServer:
    """Run Uvicorn on a pre-bound loopback socket for race-free port 0."""

    def __init__(self, *, engine: EndpointEngine, settings: EndpointSettings) -> None:
        self._settings = settings
        self._app = create_endpoint_app(engine, settings)
        self._socket: socket.socket | None = None
        self._server: uvicorn.Server | None = None
        self._thread: Thread | None = None
        self._failure: BaseException | None = None
        self._port = 0

    @property
    def port(self) -> int:
        if self._port <= 0:
            raise EndpointServerError("Endpoint server has no bound port")
        return self._port

    def start(self) -> None:
        if self._thread is not None:
            raise EndpointServerError("Endpoint ASGI server is already started")
        family = socket.AF_INET6 if ":" in self._settings.host else socket.AF_INET
        bound = socket.socket(family, socket.SOCK_STREAM)
        try:
            bound.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            bound.bind((self._settings.host, self._settings.port))
            bound.listen(2048)
            self._port = int(bound.getsockname()[1])
            config = uvicorn.Config(
                self._app,
                host=self._settings.host,
                port=self._port,
                log_level="warning",
                access_log=False,
            )
            server = uvicorn.Server(config)
            thread = Thread(
                target=self._run,
                args=(server, bound),
                name="tinysoul-endpoint",
                daemon=True,
            )
            self._socket = bound
            self._server = server
            self._thread = thread
            thread.start()
            deadline = monotonic() + 10.0
            while not server.started and thread.is_alive() and monotonic() < deadline:
                sleep(0.01)
            if not server.started:
                failure = self._failure
                self.stop()
                detail = type(failure).__name__ if failure is not None else "timeout"
                raise EndpointServerError(
                    f"Endpoint ASGI server failed to start: {detail}"
                )
        except OSError as exc:
            bound.close()
            raise EndpointServerError(f"Endpoint bind failed: {exc}") from exc

    def stop(self) -> None:
        server = self._server
        thread = self._thread
        bound = self._socket
        self._server = None
        self._thread = None
        self._socket = None
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(timeout=10.0)
        if bound is not None:
            bound.close()
        if thread is not None and thread.is_alive():
            raise EndpointServerError("Endpoint ASGI server did not stop")

    def _run(self, server: uvicorn.Server, bound: socket.socket) -> None:
        try:
            server.run(sockets=[bound])
        except BaseException as exc:
            self._failure = exc
