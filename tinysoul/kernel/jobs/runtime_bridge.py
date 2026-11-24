"""Project necessary Job failures into existing Runtime frame transfers."""

from dataclasses import dataclass

from tinysoul.runtime import RuntimeException
from tinysoul.runtime.control.exception import (
    RUNTIME_AGENT_END,
    RUNTIME_TURN_END,
    RUNTIME_STARTUP_FAILED,
)
from tinysoul.infra.config import ConfigError
from tinysoul.infra.config.errors import config_error_payload
from tinysoul.runtime.failures import exception_payload, runtime_exception
from .failures import JobError, JobFailureKind

JOBS_RUNTIME_REASON_MAP = {
    JobFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
    JobFailureKind.CONTRACT_VIOLATION: RUNTIME_TURN_END,
    JobFailureKind.SUPERVISION_FAILED: RUNTIME_TURN_END,
    JobFailureKind.EXECUTION_CLOSE_FAILED: RUNTIME_AGENT_END,
}

JOBS_FAILURE_MESSAGES = {
    JobFailureKind.CONFIGURATION_FAILED: "Job configuration is invalid.",
    JobFailureKind.CONTRACT_VIOLATION: "Job supervision contract failed.",
    JobFailureKind.SUPERVISION_FAILED: "Job supervision contract failed.",
    JobFailureKind.EXECUTION_CLOSE_FAILED: "Controlled execution could not be closed.",
}


@dataclass(frozen=True)
class RuntimeJobsBridge:
    def from_config_error(self, error: ConfigError) -> RuntimeException:
        kind = JobFailureKind.CONFIGURATION_FAILED
        return runtime_exception(
            module="jobs",
            kind=kind,
            reason=JOBS_RUNTIME_REASON_MAP[kind],
            message=JOBS_FAILURE_MESSAGES[kind],
            payload=config_error_payload(error),
        )

    def from_error(self, error: JobError) -> RuntimeException:
        return runtime_exception(
            module="jobs",
            kind=error.kind,
            reason=JOBS_RUNTIME_REASON_MAP[error.kind],
            message=JOBS_FAILURE_MESSAGES[error.kind],
            payload=exception_payload(error),
        )
