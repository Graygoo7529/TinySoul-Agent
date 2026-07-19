"""Endpoint server lifecycle managed by the application runtime."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from tinysoul.infra.json import JsonObject
from tinysoul.runtime.bridge import RuntimeEndpointBridge

from .config import EndpointSettings
from .engine import EndpointEngine
from .errors import EndpointServerError


class EndpointServer(Protocol):
    @property
    def port(self) -> int: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...


@dataclass(frozen=True)
class EndpointReady:
    host: str
    port: int
    token: str
    protocol_version: int = 1

    def to_json(self) -> JsonObject:
        return {
            "type": "endpoint.ready",
            "protocol_version": self.protocol_version,
            "host": self.host,
            "port": self.port,
            "token": self.token,
        }


class EndpointHost:
    """Start and stop the optional ASGI transport with delayed imports."""

    def __init__(
        self,
        *,
        engine: EndpointEngine,
        settings: EndpointSettings,
        ready: Callable[[EndpointReady], None] | None = None,
        runtime_bridge: RuntimeEndpointBridge | None = None,
    ) -> None:
        self._engine = engine
        self._settings = settings
        self._ready = ready
        self._runtime_bridge = runtime_bridge or RuntimeEndpointBridge()
        self._server: EndpointServer | None = None

    def start(self) -> None:
        if self._server is not None:
            raise EndpointServerError("Endpoint server is already started")
        try:
            from .server import EndpointASGIServer

            server = EndpointASGIServer(
                engine=self._engine,
                settings=self._settings,
            )
            server.start()
        except ImportError as exc:
            error = EndpointServerError(
                "Endpoint desktop dependencies are not installed"
            )
            raise self._runtime_bridge.from_endpoint_error(error) from exc
        except EndpointServerError as exc:
            raise self._runtime_bridge.from_endpoint_error(exc) from exc
        self._server = server
        try:
            if self._ready is not None:
                self._ready(
                    EndpointReady(
                        host=self._settings.host,
                        port=server.port,
                        token=self._settings.token,
                    )
                )
        except Exception as exc:
            self._server = None
            try:
                server.stop()
            except EndpointServerError:
                pass
            error = EndpointServerError("Endpoint ready handshake failed")
            raise self._runtime_bridge.from_endpoint_error(error) from exc

    def stop(self) -> None:
        server = self._server
        if server is None:
            return
        self._server = None
        server.stop()
