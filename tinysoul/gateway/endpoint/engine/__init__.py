"""Endpoint domain engines and their aggregate public entry point."""

from __future__ import annotations


from ..config import EndpointSettings
from ..events import EndpointEventBuffer
from .configuration import EndpointConfigurationEngine
from .context import EndpointEngineContext
from .contracts import (
    EndpointAgentIngress,
    EndpointConfigController,
    EndpointLifecycle,
    EndpointServices,
)
from .events import EndpointEventsEngine
from .reflection import EndpointReflectionEngine
from .runtime import EndpointControlKind, EndpointRuntimeEngine
from .workspace import EndpointResourceBlob, EndpointWorkspaceEngine


class EndpointEngine:
    """Aggregate the typed Endpoint engines over existing TinySoul modules."""

    def __init__(
        self,
        *,
        settings: EndpointSettings,
        events: EndpointEventBuffer,
        gateway: EndpointAgentIngress,
        services: EndpointServices,
        config: EndpointConfigController,
        lifecycle: EndpointLifecycle | None = None,
    ) -> None:
        context = EndpointEngineContext(
            settings=settings,
            events=events,
            _gateway=gateway,
            _services=services,
            _config=config,
            _lifecycle=lifecycle,
        )
        self._settings = settings
        self._context = context
        self.runtime = EndpointRuntimeEngine(context)
        self.reflection = EndpointReflectionEngine(context)
        self.events = EndpointEventsEngine(context)
        self.configuration = EndpointConfigurationEngine(context)
        self.workspace = EndpointWorkspaceEngine(context)

    def bind(
        self,
        *,
        gateway: EndpointAgentIngress,
        services: EndpointServices,
        config: EndpointConfigController,
    ) -> None:
        """Switch the stable Endpoint facade to a new Agent generation."""
        self._context.bind(gateway=gateway, services=services, config=config)

    def set_lifecycle(self, lifecycle: EndpointLifecycle | None) -> None:
        self._context.set_lifecycle(lifecycle)

    def unbind(self) -> None:
        self._context.unbind()

    @property
    def settings(self) -> EndpointSettings:
        return self._settings


__all__ = [
    "EndpointConfigController",
    "EndpointControlKind",
    "EndpointEngine",
    "EndpointLifecycle",
    "EndpointResourceBlob",
    "EndpointServices",
]
