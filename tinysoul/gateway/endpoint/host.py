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
from .engine import EndpointEngine, EndpointLifecycle
from .errors import EndpointServerError
from .events import EndpointEventBuffer, EndpointEventJournal


def mount_endpoint(
    assembly: AgentAssembly,
    settings: EndpointSettings,
    *,
    ready: Callable[[EndpointReady], None] | None = None,
) -> EndpointEngine:
    """Attach HTTP hosting and observation replay to an unstarted Agent."""

    host = EndpointHost(settings=settings, ready=ready)
    engine = host.bind(assembly)
    assembly.mount_service(host)
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
    """Own the Endpoint transport while allowing generation rebinding."""

    def __init__(
        self,
        *,
        settings: EndpointSettings,
        ready: Callable[[EndpointReady], None] | None = None,
        runtime_bridge: RuntimeEndpointBridge | None = None,
    ) -> None:
        self._engine: EndpointEngine | None = None
        self._settings = settings
        self._ready = ready
        self._runtime_bridge = runtime_bridge or RuntimeEndpointBridge()
        self._server: EndpointServer | None = None
        self._assembly: AgentAssembly | None = None
        self._route: ObservationRoute | None = None

    @property
    def engine(self) -> EndpointEngine:
        if self._engine is None:
            raise EndpointServerError("Endpoint is not bound to an Agent generation")
        return self._engine

    def bind(self, assembly: AgentAssembly) -> EndpointEngine:
        """Bind the stable Endpoint facade to the current Agent generation."""
        if self._assembly is assembly:
            return self.engine
        if self._assembly is not None and self._route is not None:
            self._assembly.observations.remove_route(self._route)
        if self._engine is None:
            journal = None
            if self._settings.journal_enabled:
                journal = EndpointEventJournal(
                    self._settings.journal_root
                    or (assembly.project_root / "runtime" / "endpoint" / "events"),
                    max_segment_bytes=self._settings.journal_segment_bytes,
                    max_total_bytes=self._settings.journal_total_bytes,
                )
            events = EndpointEventBuffer(
                capacity=self._settings.event_capacity,
                max_bytes=self._settings.event_bytes,
                page_bytes=self._settings.event_page_bytes,
                journal=journal,
            )
            self._engine = EndpointEngine(
                settings=self._settings,
                events=events,
                gateway=assembly.gateway,
                services=assembly.service_access,
                config=assembly.configuration,
            )
            self._route = ObservationRoute(
                sink=events, mode=ObservationLevel.MODEL
            )
        else:
            self._engine.bind(
                gateway=assembly.gateway,
                services=assembly.service_access,
                config=assembly.configuration,
            )
        assert self._route is not None
        assembly.observations.add_route(self._route)
        self._assembly = assembly
        return self.engine

    def unbind(self) -> None:
        if self._assembly is not None and self._route is not None:
            self._assembly.observations.remove_route(self._route)
        self._assembly = None
        if self._engine is not None:
            self._engine.unbind()

    def set_lifecycle(self, lifecycle: EndpointLifecycle | None) -> None:
        self.engine.set_lifecycle(lifecycle)

    async def start(self) -> None:
        if self._server is not None:
            raise EndpointServerError("Endpoint server is already started")
        try:
            from .http.server import EndpointASGIServer

            server = EndpointASGIServer(
                engine=self.engine,
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
        try:
            if server is not None:
                self._server = None
                await server.stop()
        finally:
            # A stopped host must not retain a callable lifecycle bridge.  The
            # bridge is intentionally preserved by ``unbind`` during a live
            # Agent restart, but final host shutdown closes that boundary.
            if self._engine is not None:
                self._engine.set_lifecycle(None)
            self.unbind()
