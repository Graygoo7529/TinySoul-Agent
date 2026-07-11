"""Workspace-to-runtime semantic bridge."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.infra.config import ConfigError
from tinysoul.infra.json import JsonObject
from tinysoul.workspace.errors import (
    WorkspaceContractError,
    WorkspaceInvariantError,
    WorkspaceIOError,
    WorkspaceReconciliationError,
)
from tinysoul.workspace.failures import WorkspaceFailureKind

from ..exception import RUNTIME_STARTUP_FAILED, RUNTIME_TURN_END, RuntimeException
from ._payload import config_error_payload, exception_payload, runtime_exception

WORKSPACE_RUNTIME_REASON_MAP: dict[WorkspaceFailureKind, str] = {
    WorkspaceFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
    WorkspaceFailureKind.CONTRACT_VIOLATION: RUNTIME_TURN_END,
    WorkspaceFailureKind.IO_FAILED: RUNTIME_TURN_END,
    WorkspaceFailureKind.INTERNAL_FAILURE: RUNTIME_TURN_END,
}


@dataclass(frozen=True)
class RuntimeWorkspaceBridge:
    """Convert workspace boundary failures into runtime semantic exceptions."""

    def from_failure(
        self,
        kind: WorkspaceFailureKind,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return runtime_exception(
            module="workspace",
            kind=kind,
            reason_map=WORKSPACE_RUNTIME_REASON_MAP,
            message=message,
            payload=payload,
        )

    def from_exception(
        self,
        kind: WorkspaceFailureKind,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return self.from_failure(
            kind,
            message=str(error),
            payload=exception_payload(error, payload),
        )

    def from_workspace_error(
        self,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        kind = WorkspaceFailureKind.INTERNAL_FAILURE
        if isinstance(error, (WorkspaceContractError, WorkspaceInvariantError)):
            kind = WorkspaceFailureKind.CONTRACT_VIOLATION
        elif isinstance(error, (WorkspaceIOError, WorkspaceReconciliationError)):
            kind = WorkspaceFailureKind.IO_FAILED
        return self.from_exception(kind, error, payload=payload)

    def startup_failure(
        self,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return self.from_failure(
            WorkspaceFailureKind.CONFIGURATION_FAILED,
            message=message,
            payload=payload,
        )

    def from_config_error(self, error: ConfigError) -> RuntimeException:
        return self.from_failure(
            WorkspaceFailureKind.CONFIGURATION_FAILED,
            message=error.message,
            payload=config_error_payload(error),
        )
