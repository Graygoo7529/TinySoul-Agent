"""Process facts exposed to the shared Job supervisor."""

from __future__ import annotations

from enum import StrEnum
from threading import RLock
from time import monotonic

from tinysoul.infra.concurrency import CleanupDiagnostic, JoinedOperations
from tinysoul.infra.json import JsonObject
from tinysoul.infra.process import (
    ManagedProcess,
    ManagedProcessCloseError,
    ProcessContractError,
)
from tinysoul.kernel.jobs import JobError, JobFailureKind, JobSnapshot, JobState

from .config import ExecutionSettings
from .failures import ExecutionRequestError


class _StopReason(StrEnum):
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    OUTPUT_LIMIT = "output_limit"


class ProcessJobBackend:
    """Own the OS handle; JobRegistry owns admission, terminal delivery and retention."""

    kind = "execution.process"

    def __init__(
        self,
        job_id: str,
        process: ManagedProcess,
        *,
        settings: ExecutionSettings,
        workspace_links: tuple[str, ...],
    ) -> None:
        self.job_id = job_id
        self._process = process
        self._settings = settings
        self._workspace_links = workspace_links
        self._deadline = monotonic() + settings.max_runtime_seconds
        self._stop_reason: _StopReason | None = None
        self._lock = RLock()

    async def poll(self) -> JobSnapshot:
        operations = JoinedOperations()
        result = await operations.run(self._poll)
        operations.check_cancelled()
        return result

    def _poll(self) -> JobSnapshot:
        with self._lock:
            if self._process.running():
                try:
                    stdout_size, stderr_size = self._process.output_sizes()
                except OSError as exc:
                    raise JobError(
                        "Process output is unavailable",
                        kind=JobFailureKind.SUPERVISION_FAILED,
                    ) from exc
                if stdout_size + stderr_size > self._settings.max_output_bytes:
                    self._stop(_StopReason.OUTPUT_LIMIT)
                elif monotonic() >= self._deadline:
                    self._stop(_StopReason.TIMEOUT)
                else:
                    return JobSnapshot(
                        self.job_id,
                        self.kind,
                        JobState.RUNNING,
                        result_links=self._workspace_links,
                    )
            if self._stop_reason is _StopReason.CANCELLED:
                state, reason, summary = (
                    JobState.CANCELLED,
                    "cancelled",
                    "Process execution stopped.",
                )
            elif self._stop_reason is not None:
                state, reason, summary = (
                    JobState.FAILED,
                    self._stop_reason.value,
                    "Process exceeded its execution limit.",
                )
            elif self._process.exit_code == 0:
                state, reason, summary = (
                    JobState.SUCCEEDED,
                    "exit_0",
                    "Process execution completed.",
                )
            else:
                state, reason, summary = (
                    JobState.FAILED,
                    "nonzero_exit",
                    "Process returned a non-zero exit status.",
                )
            return JobSnapshot(
                self.job_id,
                self.kind,
                state,
                summary,
                reason,
                result_links=self._workspace_links,
            )

    def _stop(self, reason: _StopReason) -> None:
        # Once natural completion is observed, a later stop preserves that fact.
        if self._process.running():
            self._stop_reason = self._stop_reason or reason
            try:
                self._process.terminate()
            except ManagedProcessCloseError as exc:
                raise JobError(
                    "Controlled process could not stop",
                    kind=JobFailureKind.EXECUTION_CLOSE_FAILED,
                ) from exc

    async def request_stop(self) -> None:
        operations = JoinedOperations()
        await operations.run(self._request_stop)
        operations.check_cancelled()

    def _request_stop(self) -> None:
        with self._lock:
            self._stop(_StopReason.CANCELLED)

    async def close_execution(self) -> tuple[CleanupDiagnostic, ...]:
        operations = JoinedOperations()
        result = await operations.run(self._close_execution)
        operations.check_cancelled()
        return result

    def _close_execution(self) -> tuple[CleanupDiagnostic, ...]:
        with self._lock:
            self._stop(_StopReason.CANCELLED)
            try:
                return self._process.close()
            except ManagedProcessCloseError as exc:
                raise JobError(
                    "Controlled process could not close",
                    kind=JobFailureKind.EXECUTION_CLOSE_FAILED,
                ) from exc

    async def cleanup(self) -> tuple[CleanupDiagnostic, ...]:
        # Logs and generated files belong to Workspace and follow its daily lifecycle.
        return ()

    async def describe(self) -> JsonObject:
        operations = JoinedOperations()
        result = await operations.run(self._describe)
        operations.check_cancelled()
        return result

    def _describe(self) -> JsonObject:
        with self._lock:
            try:
                stdout_size, stderr_size = self._process.output_sizes()
            except OSError as exc:
                raise JobError(
                    "Process output is unavailable",
                    kind=JobFailureKind.SUPERVISION_FAILED,
                ) from exc
            return {
                "exit_code": self._process.exit_code,
                "stdout_bytes": stdout_size,
                "stderr_bytes": stderr_size,
                "workspace_links": list(self._workspace_links),
            }

    def write_stdin(self, text: str, *, close: bool = False) -> int:
        if not isinstance(text, str) or not isinstance(close, bool):
            raise ExecutionRequestError("Process input requires text and a close flag")
        try:
            data = text.encode("utf-8")
        except UnicodeError as exc:
            raise ExecutionRequestError("Process input must be valid UTF-8") from exc
        if len(data) > 4096:
            raise ExecutionRequestError(
                "Process input must not exceed 4096 UTF-8 bytes"
            )
        with self._lock:
            try:
                return self._process.write_stdin(data, close=close)
            except ProcessContractError as exc:
                raise ExecutionRequestError(
                    "Process stdin is no longer writable"
                ) from exc

    def collect(
        self,
        *,
        stdout_cursor: int = 0,
        stderr_cursor: int = 0,
        max_chars: int | None = None,
    ) -> JsonObject:
        limit = self._settings.max_collect_chars if max_chars is None else max_chars
        if (
            type(stdout_cursor) is not int
            or type(stderr_cursor) is not int
            or min(stdout_cursor, stderr_cursor) < 0
            or type(limit) is not int
            or not 0 < limit <= self._settings.max_collect_chars
        ):
            raise ExecutionRequestError("Process output boundaries are invalid")
        with self._lock:
            try:
                stdout = self._process.read_stdout(
                    cursor=stdout_cursor,
                    max_chars=limit,
                    max_bytes=self._settings.max_output_bytes,
                )
                stderr = self._process.read_stderr(
                    cursor=stderr_cursor,
                    max_chars=limit,
                    max_bytes=self._settings.max_output_bytes,
                )
            except OSError as exc:
                raise JobError(
                    "Process output could not be read",
                    kind=JobFailureKind.SUPERVISION_FAILED,
                ) from exc
            return {
                **self._describe(),
                "stdout": stdout.text,
                "stderr": stderr.text,
                "stdout_cursor": stdout.next_cursor,
                "stderr_cursor": stderr.next_cursor,
                "stdout_truncated": stdout.truncated,
                "stderr_truncated": stderr.truncated,
            }
