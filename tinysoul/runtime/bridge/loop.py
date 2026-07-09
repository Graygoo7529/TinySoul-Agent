"""Loop-to-runtime semantic bridge."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.infra.config import ConfigError
from tinysoul.infra.json import JsonObject
from tinysoul.loop.errors import LoopContractError, LoopInvariantError
from tinysoul.loop.failures import LoopFailureKind

from ..exception import RUNTIME_STARTUP_FAILED, RUNTIME_TURN_END, RuntimeException
from ._payload import config_error_payload, exception_payload, runtime_exception

LOOP_RUNTIME_REASON_MAP: dict[LoopFailureKind, str] = {
    LoopFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
    LoopFailureKind.CONTRACT_VIOLATION: RUNTIME_TURN_END,
    LoopFailureKind.INTERNAL_FAILURE: RUNTIME_TURN_END,
}


@dataclass(frozen=True)
class RuntimeLoopBridge:
    """Convert loop boundary failures into runtime semantic exceptions."""

    def from_failure(
        self,
        kind: LoopFailureKind,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return runtime_exception(
            module="loop",
            kind=kind,
            reason_map=LOOP_RUNTIME_REASON_MAP,
            message=message,
            payload=payload,
        )

    def from_exception(
        self,
        kind: LoopFailureKind,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return self.from_failure(
            kind,
            message=str(error),
            payload=exception_payload(error, payload),
        )

    def from_loop_error(
        self,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        kind = LoopFailureKind.INTERNAL_FAILURE
        if isinstance(error, (LoopContractError, LoopInvariantError)):
            kind = LoopFailureKind.CONTRACT_VIOLATION
        return self.from_exception(kind, error, payload=payload)

    def startup_failure(
        self,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return self.from_failure(
            LoopFailureKind.CONFIGURATION_FAILED,
            message=message,
            payload=payload,
        )

    def from_config_error(self, error: ConfigError) -> RuntimeException:
        return self.from_failure(
            LoopFailureKind.CONFIGURATION_FAILED,
            message=error.message,
            payload=config_error_payload(error),
        )
