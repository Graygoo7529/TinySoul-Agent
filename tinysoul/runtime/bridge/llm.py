"""LLM-to-runtime semantic bridge."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.infra.config import ConfigError
from tinysoul.infra.json import JsonObject
from tinysoul.llm.failures import LLMFailureKind

from ..exception import (
    RUNTIME_STARTUP_FAILED,
    RUNTIME_TURN_END,
    RuntimeException,
)
from ._payload import config_error_payload, exception_payload, runtime_exception

LLM_RUNTIME_REASON_MAP: dict[LLMFailureKind, str] = {
    LLMFailureKind.MODEL_CHAIN_EXHAUSTED: RUNTIME_TURN_END,
    LLMFailureKind.PROVIDER_FAILURE: RUNTIME_TURN_END,
    LLMFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
    LLMFailureKind.CONTRACT_VIOLATION: RUNTIME_TURN_END,
    LLMFailureKind.INTERNAL_FAILURE: RUNTIME_TURN_END,
}


@dataclass(frozen=True)
class RuntimeLLMBridge:
    """Convert LLM boundary failures into runtime semantic exceptions."""

    def from_failure(
        self,
        kind: LLMFailureKind,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return runtime_exception(
            module="llm",
            kind=kind,
            reason_map=LLM_RUNTIME_REASON_MAP,
            message=message,
            payload=payload,
        )

    def from_exception(
        self,
        kind: LLMFailureKind,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return self.from_failure(
            kind,
            message=str(error),
            payload=exception_payload(error, payload),
        )

    def startup_failure(
        self,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return self.from_failure(
            LLMFailureKind.CONFIGURATION_FAILED,
            message=message,
            payload=payload,
        )

    def from_config_error(self, error: ConfigError) -> RuntimeException:
        return self.from_failure(
            LLMFailureKind.CONFIGURATION_FAILED,
            message=error.message,
            payload=config_error_payload(error),
        )
