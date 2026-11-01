"""Local Endpoint settings."""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path
from uuid import uuid4

from tinysoul.infra.config import ConfigError

from .errors import EndpointContractError


@dataclass(frozen=True)
class EndpointLaunchSettings:
    """Process-owned socket settings loaded from the project environment."""

    bind_host: str = "127.0.0.1"
    port: int = 1430

    def __post_init__(self) -> None:
        if not isinstance(self.bind_host, str) or not self.bind_host.strip():
            raise ConfigError(
                "Endpoint bind host must be an IP address",
                key="endpoint.bind_host",
                value=self.bind_host,
                expected="IPv4 or IPv6 address",
            )
        try:
            ip_address(self.bind_host)
        except ValueError as exc:
            raise ConfigError(
                "Endpoint bind host must be an IP address",
                key="endpoint.bind_host",
                value=self.bind_host,
                expected="IPv4 or IPv6 address",
            ) from exc
        if isinstance(self.port, bool) or not isinstance(self.port, int):
            raise ConfigError(
                "Endpoint port must be an integer",
                key="endpoint.port",
                value=self.port,
                expected="integer between 1 and 65535",
            )
        if not 1 <= self.port <= 65535:
            raise ConfigError(
                "Endpoint port must be between 1 and 65535",
                key="endpoint.port",
                value=self.port,
                expected="integer between 1 and 65535",
            )


@dataclass(frozen=True)
class EndpointSettings:
    """Validated server and bounded event settings."""

    host: str = "127.0.0.1"
    port: int = 1430
    token: str = ""
    instance_id: str = ""
    project_identity: str = ""
    event_capacity: int = 2000
    event_bytes: int = 32 * 1024 * 1024
    event_page_bytes: int = 1024 * 1024
    journal_enabled: bool = True
    journal_root: Path | None = None
    journal_segment_bytes: int = 8 * 1024 * 1024
    journal_total_bytes: int = 256 * 1024 * 1024
    websocket_heartbeat_seconds: float = 15.0
    max_request_bytes: int = 8 * 1024 * 1024
    max_resource_chars: int = 2 * 1024 * 1024
    max_resource_bytes: int = 8 * 1024 * 1024

    def __post_init__(self) -> None:
        if not isinstance(self.host, str) or not self.host.strip():
            raise EndpointContractError("Endpoint host must be an IP address")
        try:
            ip_address(self.host)
        except ValueError as exc:
            raise EndpointContractError(
                "Endpoint host must be an IP address"
            ) from exc
        if isinstance(self.port, bool) or not isinstance(self.port, int):
            raise EndpointContractError("Endpoint port must be an integer")
        if not 0 <= self.port <= 65535:
            raise EndpointContractError("Endpoint port must be between 0 and 65535")
        if not isinstance(self.token, str) or len(self.token) < 32:
            raise EndpointContractError(
                "Endpoint bearer token must contain at least 32 characters"
            )
        instance_id = self.instance_id or f"instance_{uuid4().hex}"
        if not isinstance(instance_id, str) or not instance_id.strip():
            raise EndpointContractError("Endpoint instance_id must be non-empty")
        if not isinstance(self.project_identity, str):
            raise EndpointContractError("Endpoint project_identity must be text")
        if (
            isinstance(self.websocket_heartbeat_seconds, bool)
            or not isinstance(self.websocket_heartbeat_seconds, (int, float))
            or self.websocket_heartbeat_seconds <= 0
        ):
            raise EndpointContractError(
                "Endpoint websocket heartbeat must be positive"
            )
        if not isinstance(self.journal_enabled, bool):
            raise EndpointContractError("Endpoint journal_enabled must be a bool")
        if self.journal_root is not None and not isinstance(self.journal_root, Path):
            raise EndpointContractError("Endpoint journal_root must be a Path")
        object.__setattr__(self, "instance_id", instance_id.strip())
        for name in (
            "event_capacity",
            "event_bytes",
            "event_page_bytes",
            "journal_segment_bytes",
            "journal_total_bytes",
            "max_request_bytes",
            "max_resource_chars",
            "max_resource_bytes",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise EndpointContractError(f"Endpoint {name} must be positive")
        if self.journal_segment_bytes > self.journal_total_bytes:
            raise EndpointContractError(
                "Endpoint journal_segment_bytes cannot exceed journal_total_bytes"
            )
