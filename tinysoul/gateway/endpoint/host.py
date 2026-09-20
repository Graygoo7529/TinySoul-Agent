"""Endpoint server lifecycle managed by the application runtime."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from tinysoul.agent.composition.assembly import AgentAssembly
from tinysoul.agent.observation.outputs import ObservationRoute
from tinysoul.runtime import ObservationLevel

from tinysoul.infra.json import JsonObject
from tinysoul.gateway.endpoint.runtime_bridge import RuntimeEndpointBridge

from .config import EndpointSettings
from .engine import EndpointEngine
from .errors import EndpointServerError
from .events import EndpointEventBuffer, EndpointEventJournal


def mount_endpoint(
    assembly: AgentAssembly,
    settings: EndpointSettings,
    *,
    ready: Callable[[EndpointReady], None] | None = None,
) -> EndpointEngine:
    """Attach HTTP hosting and observation replay to an unstarted Agent."""

    journal = None
    if settings.journal_enabled:
        journal = EndpointEventJournal(
            settings.journal_root
            or (assembly.project_root / "runtime" / "endpoint" / "events"),
            max_segment_bytes=settings.journal_segment_bytes,
            max_total_bytes=settings.journal_total_bytes,
        )
    events = EndpointEventBuffer(
        capacity=settings.event_capacity,
        max_bytes=settings.event_bytes,
        page_bytes=settings.event_page_bytes,
        journal=journal,
    )
    engine = EndpointEngine(
        settings=settings,
        events=events,
        gateway=assembly.gateway,
        services=assembly.service_access,
        config=assembly.configuration,
    )
    assembly.mount_service(EndpointHost(engine=engine, settings=settings, ready=ready))
    assembly.observations.add_route(
        ObservationRoute(sink=events, mode=ObservationLevel.MODEL)
    )
    return engine


class EndpointServer(Protocol):
    @property
    def port(self) -> int: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


@dataclass(frozen=True)
class EndpointReady:
    host: str
    port: int
    token: str
    instance_id: str
    project_identity: str
    protocol_version: int = 2

    def to_json(self) -> JsonObject:
        return {
            "type": "endpoint.ready",
            "protocol_version": self.protocol_version,
            "host": self.host,
            "port": self.port,
            "token": self.token,
            "instance_id": self.instance_id,
            "project_identity": self.project_identity,
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

    async def start(self) -> None:
        if self._server is not None:
            raise EndpointServerError("Endpoint server is already started")
        try:
            from .http.server import EndpointASGIServer

            server = EndpointASGIServer(
                engine=self._engine,
                settings=self._settings,
            )
            await server.start()
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
                        instance_id=self._settings.instance_id,
                        project_identity=self._settings.project_identity,
                    )
                )
        except Exception as exc:
            self._server = None
            try:
                await server.stop()
            except EndpointServerError:
                pass
            error = EndpointServerError("Endpoint ready handshake failed")
            raise self._runtime_bridge.from_endpoint_error(error) from exc

    async def stop(self) -> None:
        server = self._server
        if server is None:
            return
        self._server = None
        await server.stop()
