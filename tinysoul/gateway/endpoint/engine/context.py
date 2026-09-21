"""Endpoint dependencies over the Agent's public admission and services."""

from collections.abc import Callable
from dataclasses import dataclass

from ..config import EndpointSettings
from ..events import EndpointEventBuffer
from ..errors import EndpointRequestError
from .contracts import (
    EndpointAgentIngress,
    EndpointConfigController,
    EndpointLifecycle,
    EndpointServices,
)


@dataclass
class EndpointEngineContext:
    settings: EndpointSettings
    events: EndpointEventBuffer
    _gateway: EndpointAgentIngress | None
    _services: EndpointServices | None
    _config: EndpointConfigController | None
    _available: Callable[[], bool]
    _lifecycle: EndpointLifecycle | None = None

    @property
    def gateway(self) -> EndpointAgentIngress:
        if self._gateway is None or not self.available:
            raise self._unavailable()
        return self._gateway

    @property
    def bound(self) -> bool:
        return (
            self._gateway is not None
            and self._services is not None
            and self._config is not None
        )

    @property
    def available(self) -> bool:
        return self.bound and self._available()

    @property
    def services(self) -> EndpointServices:
        if self._services is None or not self.available:
            raise self._unavailable()
        return self._services

    @property
    def config(self) -> EndpointConfigController:
        if self._config is None or not self.available:
            raise self._unavailable()
        return self._config

    @property
    def lifecycle(self) -> EndpointLifecycle:
        if self._lifecycle is None:
            raise EndpointRequestError(
                status_code=409,
                code="endpoint.lifecycle_unavailable",
                message="Endpoint lifecycle control is not attached.",
            )
        return self._lifecycle

    def bind(
        self,
        *,
        gateway: EndpointAgentIngress,
        services: EndpointServices,
        config: EndpointConfigController,
    ) -> None:
        self._gateway = gateway
        self._services = services
        self._config = config

    def unbind(self) -> None:
        self._gateway = None
        self._services = None
        self._config = None

    def set_lifecycle(self, lifecycle: EndpointLifecycle | None) -> None:
        self._lifecycle = lifecycle

    @staticmethod
    def _unavailable() -> EndpointRequestError:
        return EndpointRequestError(
            status_code=409,
            code="service.unavailable",
            message="Agent generation is not currently available.",
        )

    def config_controller(self) -> EndpointConfigController:
        return self.config
