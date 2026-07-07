"""Workspace-to-runtime semantic bridge."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.infra.config import ConfigError
from tinysoul.infra.json import JsonObject, to_json_value
from tinysoul.workspace.errors import (
    WorkspaceContractError,
    WorkspaceInvariantError,
    WorkspaceIOError,
)
from tinysoul.workspace.failures import WorkspaceFailureKind

from ..exception import RUNTIME_STARTUP_FAILED, RUNTIME_TURN_END, RuntimeException

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
        runtime_payload: JsonObject = {}
        if payload is not None:
            runtime_payload = payload
        runtime_payload = {**runtime_payload, "module": "workspace", "kind": kind.value}
        return RuntimeException(
            reason=WORKSPACE_RUNTIME_REASON_MAP[kind],
            message=message,
            payload=runtime_payload,
        )

    def from_exception(
        self,
        kind: WorkspaceFailureKind,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        runtime_payload: JsonObject = {"error_type": type(error).__name__}
        if payload is not None:
            runtime_payload = {**runtime_payload, **payload}
        return self.from_failure(kind, message=str(error), payload=runtime_payload)

    def from_workspace_error(
        self,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        kind = WorkspaceFailureKind.INTERNAL_FAILURE
        if isinstance(error, (WorkspaceContractError, WorkspaceInvariantError)):
            kind = WorkspaceFailureKind.CONTRACT_VIOLATION
        elif isinstance(error, WorkspaceIOError):
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
        payload: JsonObject = {
            "key": error.key,
            "source": error.source,
            "expected": error.expected,
        }
        if error.value is not None:
            payload = {**payload, "value": to_json_value(error.value)}
        return self.from_failure(
            WorkspaceFailureKind.CONFIGURATION_FAILED,
            message=error.message,
            payload=payload,
        )
