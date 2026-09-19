"""Project necessary Job failures into existing Runtime frame transfers."""

from dataclasses import dataclass

from tinysoul.runtime import RuntimeException
from tinysoul.runtime.control.exception import (
    RUNTIME_AGENT_END,
    RUNTIME_TURN_END,
    RUNTIME_STARTUP_FAILED,
)
from tinysoul.infra.config import ConfigError
from tinysoul.runtime.failures import runtime_exception
from .failures import JobError, JobFailureKind

_REASONS = {
    JobFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
    JobFailureKind.CONTRACT_VIOLATION: RUNTIME_TURN_END,
    JobFailureKind.SUPERVISION_FAILED: RUNTIME_TURN_END,
    JobFailureKind.EXECUTION_CLOSE_FAILED: RUNTIME_AGENT_END,
}


@dataclass(frozen=True)
class RuntimeJobsBridge:
    def from_config_error(self, error: ConfigError) -> RuntimeException:
        return runtime_exception(
            module="jobs",
            kind=JobFailureKind.CONFIGURATION_FAILED,
            reason=RUNTIME_STARTUP_FAILED,
            message="Job configuration is invalid.",
            payload={"error_type": type(error).__name__, "key": error.key},
        )

    def from_error(self, error: JobError) -> RuntimeException:
        return runtime_exception(
            module="jobs",
            kind=error.kind,
            reason=_REASONS[error.kind],
            message=(
                "Controlled execution could not be closed."
                if error.kind is JobFailureKind.EXECUTION_CLOSE_FAILED
                else "Job supervision contract failed."
            ),
            payload={"error_type": type(error).__name__},
        )
