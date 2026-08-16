"""Endpoint domain engines and their aggregate public entry point."""

from __future__ import annotations

from typing import Generic

from ..config import EndpointSettings
from ..events import EndpointEventBuffer
from .configuration import EndpointConfigurationEngine
from .context import EndpointEngineContext
from .contracts import (
    EndpointAppGateway,
    EndpointConfigController,
    EndpointGenerationT,
    EndpointMaintenanceStatus,
    EndpointRuntimeGeneration,
)
from .events import EndpointEventsEngine
from .maintenance import EndpointMaintenanceEngine
from .runtime import EndpointControlKind, EndpointRuntimeEngine
from .workspace import EndpointResourceBlob, EndpointWorkspaceEngine
from tinysoul.workspace import WorkspaceEngine
from tinysoul.runtime import RuntimeHandle


class EndpointEngine(Generic[EndpointGenerationT]):
    """Aggregate the typed Endpoint engines over existing TinySoul modules."""

    def __init__(
        self,
        *,
        settings: EndpointSettings,
        events: EndpointEventBuffer,
        gateway: EndpointAppGateway,
        workspace: WorkspaceEngine,
        maintenance: EndpointMaintenanceStatus,
        config: EndpointConfigController | None = None,
        runtime_handle: RuntimeHandle[EndpointGenerationT] | None = None,
    ) -> None:
        context = EndpointEngineContext(
            settings=settings,
            events=events,
            gateway=gateway,
            workspace=workspace,
            maintenance=maintenance,
            config=config,
            runtime_handle=runtime_handle,
        )
        self._settings = settings
        self.runtime = EndpointRuntimeEngine(context)
        self.maintenance = EndpointMaintenanceEngine(context)
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
    "EndpointGenerationT",
    "EndpointResourceBlob",
    "EndpointRuntimeGeneration",
]
