"""Shared dependency context for Endpoint engines."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Generic

from tinysoul.runtime import RuntimeHandle
from tinysoul.workspace import WorkspaceEngine

from ..config import EndpointSettings
from ..events import EndpointEventBuffer
from .contracts import (
    EndpointAppGateway,
    EndpointConfigController,
    EndpointGenerationT,
    EndpointMaintenanceStatus,
)


@dataclass(frozen=True)
class EndpointEngineContext(Generic[EndpointGenerationT]):
    settings: EndpointSettings
    events: EndpointEventBuffer
    gateway: EndpointAppGateway
    workspace: WorkspaceEngine
    maintenance: EndpointMaintenanceStatus
    config: EndpointConfigController | None
    runtime_handle: RuntimeHandle[EndpointGenerationT] | None

    @contextmanager
    def workspace_lease(self):
        if self.runtime_handle is None:
            yield self.maintenance, self.workspace
            return
        with self.runtime_handle.read() as generation:
            yield generation.maintenance, generation.workspace

    def config_controller(self) -> EndpointConfigController:
        controller = self.config
        if controller is None:
            from ..errors import EndpointRequestError

            raise EndpointRequestError(
                status_code=404,
                code="config.unavailable",
                message="Configuration control is not available.",
            )
        return controller
