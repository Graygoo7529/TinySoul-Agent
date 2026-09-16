"""Shared dependency context for Endpoint engines."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Generic, Iterator

from tinysoul.runtime import RuntimeHandle
from tinysoul.plugins.workspace import WorkspaceEngine
from tinysoul.agent.services import AgentRuntimeServices
from tinysoul.infra.json import JsonObject

from ..config import EndpointSettings
from ..events import EndpointEventBuffer
from .contracts import (
    EndpointAgentIngress,
    EndpointConfigController,
    EndpointGenerationT,
    EndpointReflectionStatus,
    EndpointDayStatus,
)


@dataclass(frozen=True)
class EndpointEngineContext(Generic[EndpointGenerationT]):
    settings: EndpointSettings
    events: EndpointEventBuffer
    gateway: EndpointAgentIngress
    workspace: WorkspaceEngine
    maintenance: EndpointReflectionStatus
    day: EndpointDayStatus
    config: EndpointConfigController | None
    runtime_handle: RuntimeHandle[EndpointGenerationT] | None

    @contextmanager
    def services_lease(self) -> Iterator[AgentRuntimeServices | None]:
        """Lease the read-only services projection for one endpoint operation."""

        if self.runtime_handle is None:
            yield None
            return
        with self.runtime_handle.read() as generation:
            yield generation

    @contextmanager
    def workspace_lease(self):
        with self.services_lease() as services:
            if services is None:
                yield self.day, self.workspace
            else:
                yield services.day, services.workspace

    def runtime_status(self, *, credentials: bool = False) -> JsonObject:
        handle = self.runtime_handle
        if handle is None:
            return {"generation_id": "", "activity": "idle"}
        with handle.read() as services:
            snapshot = handle.snapshot()
            result: JsonObject = {
                "generation_id": snapshot.generation_id,
                "activity": snapshot.activity.value,
                "activation": snapshot.activation.value,
            }
            if credentials:
                result["llm"] = {"providers": [
                    {
                        "id": item.provider_id,
                        "credential_state": item.state.value,
                        "api_key_envs": list(item.api_key_envs),
                    }
                    for item in services.llm_provider_credentials
                ]}
            return result

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
