"""Endpoint domain engines and their aggregate public entry point."""

from __future__ import annotations

from collections.abc import Callable

from tinysoul.gateway.presentation import PresentationService

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
from .presentation import EndpointPresentationEngine
from .reflection import EndpointReflectionEngine
from .resources import EndpointResourcesEngine
from .runtime import EndpointControlKind, EndpointRuntimeEngine
from .workspace import EndpointWorkspaceEngine


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
        presentation: PresentationService,
        available: Callable[[], bool],
        lifecycle: EndpointLifecycle | None = None,
    ) -> None:
        context = EndpointEngineContext(
            settings=settings,
            events=events,
            _gateway=gateway,
            _services=services,
            _config=config,
            _available=available,
            _lifecycle=lifecycle,
        )
        self._settings = settings
        self._context = context
        self.runtime = EndpointRuntimeEngine(context)
        self.reflection = EndpointReflectionEngine(context)
        self.events = EndpointEventsEngine(context)
        self.configuration = EndpointConfigurationEngine(context)
        self.workspace = EndpointWorkspaceEngine(context)
        self.resources = EndpointResourcesEngine(context)
        self.presentation = EndpointPresentationEngine(
            presentation, max_resource_bytes=settings.max_resource_bytes
        )

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

    @property
    def inspection(self) -> EndpointServices:
        """Read-only SDK projections; transport never owns their state."""
        return self._context.services


__all__ = [
    "EndpointConfigController",
    "EndpointControlKind",
    "EndpointEngine",
    "EndpointLifecycle",
    "EndpointServices",
]
