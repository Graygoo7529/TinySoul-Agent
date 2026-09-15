"""LLM-to-runtime semantic bridge."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.infra.config import ConfigError
from tinysoul.infra.config.errors import config_error_payload
from tinysoul.infra.json import JsonObject
from tinysoul.runtime import RUNTIME_STARTUP_FAILED, RUNTIME_TURN_END, RuntimeException
from tinysoul.runtime.failures import exception_payload, runtime_exception
from .failures import LLM_CONTEXT_CAPACITY_EXCEEDED, LLMFailureKind

LLM_RUNTIME_REASON_MAP: dict[LLMFailureKind, str] = {
    LLMFailureKind.MODEL_CHAIN_EXHAUSTED: RUNTIME_TURN_END,
    LLMFailureKind.MODEL_CONTEXT_PRESSURE: LLM_CONTEXT_CAPACITY_EXCEEDED,
    LLMFailureKind.MODEL_CONTEXT_LIMIT_REACHED: RUNTIME_TURN_END,
    LLMFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
    LLMFailureKind.CONTRACT_VIOLATION: RUNTIME_TURN_END,
    LLMFailureKind.INTERNAL_FAILURE: RUNTIME_TURN_END,
}


LLM_FAILURE_MESSAGES: dict[LLMFailureKind, str] = {
    LLMFailureKind.MODEL_CHAIN_EXHAUSTED: "LLM model chain is exhausted.",
    LLMFailureKind.MODEL_CONTEXT_PRESSURE: "LLM request exceeds model context capacity.",
    LLMFailureKind.MODEL_CONTEXT_LIMIT_REACHED: "LLM request exceeds model context capacity.",
    LLMFailureKind.CONFIGURATION_FAILED: "LLM configuration is invalid.",
    LLMFailureKind.CONTRACT_VIOLATION: "LLM call violated its contract.",
    LLMFailureKind.INTERNAL_FAILURE: "LLM operation failed internally.",
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
            reason=LLM_RUNTIME_REASON_MAP[kind],
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
            message=LLM_FAILURE_MESSAGES[kind],
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
            message=LLM_FAILURE_MESSAGES[LLMFailureKind.CONFIGURATION_FAILED],
            payload=config_error_payload(error),
        )
