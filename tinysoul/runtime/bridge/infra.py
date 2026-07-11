"""Infra-to-runtime semantic bridge."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.infra.config import ConfigError
from tinysoul.infra.failures import InfraFailureKind
from tinysoul.infra.json import JsonObject

from ..exception import RUNTIME_STARTUP_FAILED, RuntimeException
from ._payload import config_error_payload, runtime_exception

INFRA_RUNTIME_REASON_MAP: dict[InfraFailureKind, str] = {
    InfraFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
}


@dataclass(frozen=True)
class RuntimeInfraBridge:
    """Convert infra boundary failures into runtime semantic exceptions."""

    def from_failure(
        self,
        kind: InfraFailureKind,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return runtime_exception(
            module="infra",
            kind=kind,
            reason_map=INFRA_RUNTIME_REASON_MAP,
            message=message,
            payload=payload,
        )

    def startup_failure(
        self,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return self.from_failure(
            InfraFailureKind.CONFIGURATION_FAILED,
            message=message,
            payload=payload,
        )

    def from_config_error(self, error: ConfigError) -> RuntimeException:
        return self.from_failure(
            InfraFailureKind.CONFIGURATION_FAILED,
            message=error.message,
            payload=config_error_payload(error),
        )
