"""Subprocess-backed action execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from tinysoul.action.core.errors import ActionContractError
from tinysoul.action.core.executor import ActionExecutionControl

from .process import (
    ManagedProcessRequest,
    ManagedProcessRunner,
    ManagedProcessStartError,
)


class ProcessStatus(StrEnum):
    """Stable completion status for one controlled process."""

    COMPLETED = "completed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    START_FAILED = "start_failed"


@dataclass(frozen=True)
class ProcessRequest:
    """Validated host-owned process invocation."""

    argv: tuple[str, ...]
    cwd: str | None = None
    env: Mapping[str, str] | None = None
    inherit_env: bool = True
    stdin_text: str | None = None
    stdout_limit: int = 8000
    stderr_limit: int = 4000

    def __post_init__(self) -> None:
        if not self.argv or any(not isinstance(item, str) or not item for item in self.argv):
            raise ActionContractError("Process argv must contain non-empty strings")
        if self.cwd is not None and (not isinstance(self.cwd, str) or not self.cwd):
            raise ActionContractError("Process cwd must be a non-empty string or None")
        if self.env is not None and any(
            not isinstance(key, str)
            or not key
            or not isinstance(value, str)
            for key, value in self.env.items()
        ):
            raise ActionContractError("Process env must contain string keys and values")
        if not isinstance(self.inherit_env, bool):
            raise ActionContractError("Process inherit_env must be boolean")
        if self.stdin_text is not None and not isinstance(self.stdin_text, str):
            raise ActionContractError("Process stdin must be text or None")
        for name in ("stdout_limit", "stderr_limit"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ActionContractError(f"Process {name} must be positive")


@dataclass(frozen=True)
class ProcessOutcome:
    """Bounded result from one controlled process."""

    status: ProcessStatus
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    error_type: str = ""
    error_message: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.status, ProcessStatus):
            raise ActionContractError("Process outcome status is invalid")
        if self.status is ProcessStatus.START_FAILED:
            if not self.error_type or not self.error_message:
                raise ActionContractError(
                    "Failed process start requires error type and message"
                )
        elif self.error_type or self.error_message:
            raise ActionContractError(
                "Completed process outcome cannot carry a start error"
            )


class ControlledProcessRunner:
    """Run a fixed process with Action cancellation and hard termination."""

    def run(
        self,
        request: ProcessRequest,
        control: ActionExecutionControl,
    ) -> ProcessOutcome:
        if control.is_cancelled():
            return ProcessOutcome(status=ProcessStatus.CANCELLED)
        if control.is_expired():
            return ProcessOutcome(status=ProcessStatus.TIMED_OUT)
        try:
            handle = ManagedProcessRunner().start(
                ManagedProcessRequest(
                    argv=request.argv,
                    cwd=request.cwd,
                    env=request.env,
                    inherit_env=request.inherit_env,
                    stdin_text=request.stdin_text,
                )
            )
        except ManagedProcessStartError as exc:
            return ProcessOutcome(
                status=ProcessStatus.START_FAILED,
                error_type=type(exc.__cause__).__name__ if exc.__cause__ else type(exc).__name__,
                error_message=str(exc),
            )
        with handle:
            def terminate_on_cancel(_reason: str) -> None:
                handle.terminate()

            control.add_cancel_callback(terminate_on_cancel)
            status = ProcessStatus.COMPLETED
            try:
                completed = handle.wait(control.remaining_seconds())
                if completed is None:
                    control.request_cancel("timeout")
                    handle.terminate()
                    status = ProcessStatus.TIMED_OUT
            finally:
                control.remove_cancel_callback(terminate_on_cancel)
            if status is ProcessStatus.COMPLETED and control.is_cancelled():
                status = ProcessStatus.CANCELLED
            stdout = handle.read_stdout(
                cursor=0,
                max_chars=request.stdout_limit,
                max_bytes=(request.stdout_limit + 1) * 4,
            )
            stderr = handle.read_stderr(
                cursor=0,
                max_chars=request.stderr_limit,
                max_bytes=(request.stderr_limit + 1) * 4,
            )
            return ProcessOutcome(
                status=status,
                exit_code=handle.exit_code,
                stdout=stdout.text,
                stderr=stderr.text,
                stdout_truncated=stdout.truncated,
                stderr_truncated=stderr.truncated,
            )
