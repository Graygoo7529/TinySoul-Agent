"""Workspace-to-runtime semantic bridge."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.infra.config import ConfigError
from tinysoul.infra.config.errors import config_error_payload
from tinysoul.infra.json import JsonObject
from tinysoul.runtime import RUNTIME_STARTUP_FAILED, RUNTIME_TURN_END, RuntimeException
from tinysoul.runtime.failures import exception_payload, runtime_exception
from tinysoul.plugins.workspace.errors import (
    WorkspaceContractError,
    WorkspaceInvariantError,
    WorkspaceIOError,
    WorkspaceReconciliationError,
)
from tinysoul.plugins.workspace.failures import (
    WorkspaceFailureKind,
)

WORKSPACE_RUNTIME_REASON_MAP: dict[WorkspaceFailureKind, str] = {
    WorkspaceFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
    WorkspaceFailureKind.CONTRACT_VIOLATION: RUNTIME_TURN_END,
    WorkspaceFailureKind.IO_FAILED: RUNTIME_TURN_END,
    WorkspaceFailureKind.INTERNAL_FAILURE: RUNTIME_TURN_END,
}


WORKSPACE_FAILURE_MESSAGES: dict[WorkspaceFailureKind, str] = {
    WorkspaceFailureKind.CONFIGURATION_FAILED: "Workspace configuration is invalid.",
    WorkspaceFailureKind.CONTRACT_VIOLATION: "Workspace call violated its contract.",
    WorkspaceFailureKind.IO_FAILED: "Workspace storage operation failed.",
    WorkspaceFailureKind.INTERNAL_FAILURE: "Workspace operation failed internally.",
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
            reason=WORKSPACE_RUNTIME_REASON_MAP[kind],
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
            message=WORKSPACE_FAILURE_MESSAGES[kind],
            payload=exception_payload(error, payload),
        )

    def from_workspace_error(
        self,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        kind = WorkspaceFailureKind.INTERNAL_FAILURE
        if isinstance(error, WorkspaceContractError):
            kind = WorkspaceFailureKind.CONTRACT_VIOLATION
        elif isinstance(error, WorkspaceInvariantError):
            kind = WorkspaceFailureKind.INTERNAL_FAILURE
        elif isinstance(error, (WorkspaceIOError, WorkspaceReconciliationError)):
            kind = WorkspaceFailureKind.IO_FAILED
        facts = dict(payload or {})
        if isinstance(error, WorkspaceIOError) and error.committed_links:
            facts["committed_links"] = list(error.committed_links)
        return self.from_exception(kind, error, payload=facts)

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
            message=WORKSPACE_FAILURE_MESSAGES[
                WorkspaceFailureKind.CONFIGURATION_FAILED
            ],
            payload=config_error_payload(error),
        )
