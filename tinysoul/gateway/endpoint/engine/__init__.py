"""Endpoint domain engines and their aggregate public entry point."""

from __future__ import annotations


from ..config import EndpointSettings
from ..events import EndpointEventBuffer
from .configuration import EndpointConfigurationEngine
from .context import EndpointEngineContext
from .contracts import (
    EndpointAgentIngress,
    EndpointConfigController,
    EndpointServices,
)
from .events import EndpointEventsEngine
from .maintenance import EndpointReflectionEngine
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
    ) -> None:
        context = EndpointEngineContext(
            settings=settings,
            events=events,
            gateway=gateway,
            services=services,
            config=config,
        )
        self._settings = settings
        self.runtime = EndpointRuntimeEngine(context)
        self.maintenance = EndpointReflectionEngine(context)
        self.events = EndpointEventsEngine(context)
        self.configuration = EndpointConfigurationEngine(context)
        self.workspace = EndpointWorkspaceEngine(context)

    @property
    def settings(self) -> EndpointSettings:
        return self._settings


__all__ = [
    "EndpointConfigController",
    "EndpointControlKind",
    "EndpointEngine",
    "EndpointResourceBlob",
    "EndpointServices",
]
