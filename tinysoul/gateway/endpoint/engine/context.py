"""Endpoint dependencies over the Agent's public admission and services."""

from dataclasses import dataclass

from .contracts import EndpointServices
from ..config import EndpointSettings
from ..events import EndpointEventBuffer
from .contracts import EndpointAgentIngress, EndpointConfigController


@dataclass(frozen=True)
class EndpointEngineContext:
    settings: EndpointSettings
    events: EndpointEventBuffer
    gateway: EndpointAgentIngress
    services: EndpointServices
    config: EndpointConfigController

    def config_controller(self) -> EndpointConfigController:
        return self.config
