"""Turn-scoped supervised Script execution jobs."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys
from threading import RLock
from time import monotonic
from uuid import uuid4
from typing import Protocol

from tinysoul.action import ActionExecutionControl
from tinysoul.action.backends import (
    ManagedProcess,
    ManagedProcessRequest,
    ManagedProcessRunner,
    ManagedProcessStartError,
)
from tinysoul.infra import JsonObject, StagingDirectoryManager
from tinysoul.infra.filesystem import file_digest
from tinysoul.context import (
    SIGNAL_INPUT_APPEND,
    ContextError,
    parse_input_append_signal,
)
from tinysoul.loop.signals import (
    SIGNAL_CONTROL_REQUEST,
    LoopControlKind,
    parse_control_request_signal,
)
from tinysoul.loop import LoopError
from tinysoul.runtime import (
    RunLevel,
    RuntimeException,
    Signal,
    SignalBus,
    SignalWatch,
)
from tinysoul.workspace import (
    WorkspaceManifest,
    WorkspaceMirror,
    WorkspaceMirrorConflict,
    WorkspaceMirrorService,
)

from .config import ScriptSettings
from .errors import ScriptContractError, ScriptExecutionError, ScriptStateError
from .models import ScriptJobState, ScriptLanguage, ScriptSource


@dataclass
class _ScriptJob:
    execution_id: str
    turn_id: str
    source: ScriptSource
    staging_root: Path
    mirror: WorkspaceMirror
    process: ManagedProcess
    started_at: float
    deadline: float
    signal_watch: SignalWatch
    stdout_cursor: int = 0
    stderr_cursor: int = 0
    state: ScriptJobState = ScriptJobState.RUNNING
    failure_reason: str = ""
    supervision_cycles: int = 0
    next_cycle_at: float = 0.0


@dataclass(frozen=True)
class ScriptJobObservation:
    payload: JsonObject
    timed_out: bool = False
    failed: bool = False


@dataclass(frozen=True)
class ScriptJobApply:
    payload: JsonObject
    manifest: WorkspaceManifest


class ScriptRuntimeBridge(Protocol):
    def from_script_error(
        self,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException: ...


class ScriptJobManager:
    """Own at most one unresolved process job per active Turn."""

    def __init__(
        self,
        *,
        settings: ScriptSettings,
        mirror_service: WorkspaceMirrorService,
        staging: StagingDirectoryManager,
        process_runner: ManagedProcessRunner | None = None,
        runtime_bridge: ScriptRuntimeBridge | None = None,
    ) -> None:
        self._settings = settings
        self._mirrors = mirror_service
        self._staging = staging
        self._process_runner = process_runner or ManagedProcessRunner()
        self._runtime_bridge = runtime_bridge
        self._jobs: dict[str, _ScriptJob] = {}
        self._by_turn: dict[str, str] = {}
        self._lock = RLock()

    def start(
        self,
        *,
        turn_id: str,
        source: ScriptSource,
        args: tuple[str, ...],
        control: ActionExecutionControl,
        bus: SignalBus | None,
    ) -> ScriptJobObservation:
        if not turn_id:
            raise ScriptContractError("Script run requires a Turn id")
        signal_watch = bus.watch() if bus is not None else SignalBus().watch()
        with self._lock:
            if turn_id in self._by_turn:
                signal_watch.close()
                raise ScriptStateError("The current Turn already has an unresolved Script job")
            execution_id = f"script_{uuid4().hex}"
            staging_root: Path | None = None
            try:
                staging_root = self._staging.create("script-job")
                mirror = self._mirrors.create(staging_root / "workspace")
                if source.link.startswith("workspace:"):
                    baseline = next(
                        (item for item in mirror.entries if item.link == source.link),
                        None,
                    )
                    if baseline is None or baseline.digest != source.digest:
                        raise ScriptContractError(
                            "Script Workspace source changed after policy validation"
                        )
                script_path = self._execution_source(source, staging_root, mirror)
                if file_digest(script_path) != source.snapshot_digest:
                    raise ScriptContractError(
                        "Script source changed after policy validation"
                    )
                process = self._process_runner.start(
                    ManagedProcessRequest(
                        argv=self._argv(source.language, script_path, args),
                        cwd=str(mirror.root),
                        env=self._environment(mirror.root),
                        inherit_env=False,
                    ),
                    capture_root=staging_root / "logs",
                )
            except Exception as exc:
                signal_watch.close()
                if staging_root is not None:
                    try:
                        self._staging.cleanup(staging_root)
                    except Exception:
                        pass
                if isinstance(exc, ScriptContractError):
                    raise
                if not isinstance(exc, (OSError, ManagedProcessStartError)):
                    raise
                raise ScriptExecutionError("Script process could not be started") from exc
            now = monotonic()
            job = _ScriptJob(
                execution_id=execution_id,
                turn_id=turn_id,
                source=source,
                staging_root=staging_root,
                mirror=mirror,
                process=process,
                started_at=now,
                deadline=now + self._settings.max_runtime_seconds,
                signal_watch=signal_watch,
                next_cycle_at=now + self._settings.cycle_wait_seconds,
            )
            self._jobs[execution_id] = job
            self._by_turn[turn_id] = execution_id
        return self._wait_job(
            job,
            wait_seconds=self._settings.initial_wait_seconds,
            control=control,
            bus=bus,
        )

    def wait(
        self,
        *,
        turn_id: str,
        execution_id: str,
        wait_seconds: int,
        control: ActionExecutionControl,
        bus: SignalBus | None,
    ) -> ScriptJobObservation:
        job = self._job(turn_id, execution_id)
        if job.state is not ScriptJobState.RUNNING:
            self._refresh(job)
            return self._observation(job)
        if not (
            self._settings.min_wait_seconds
            <= wait_seconds
            <= self._settings.max_wait_seconds
        ):
            raise ScriptContractError(
                "Script wait_seconds is outside the configured boundaries"
            )
        return self._wait_job(
            job,
            wait_seconds=wait_seconds,
            control=control,
            bus=bus,
        )

    def stop(self, *, turn_id: str, execution_id: str) -> ScriptJobObservation:
        job = self._job(turn_id, execution_id)
        self._refresh(job)
        if job.state is ScriptJobState.RUNNING:
            job.process.terminate()
            job.process.wait(5.0)
            job.state = ScriptJobState.STOPPED
            job.failure_reason = "stopped_by_agent"
        return self._observation(job)

    def read_candidate(
        self,
        *,
        turn_id: str,
        execution_id: str,
        path: str,
        cursor: int,
        max_chars: int,
    ) -> JsonObject:
        job = self._job(turn_id, execution_id)
        if max_chars > self._settings.max_candidate_read_chars:
            raise ScriptContractError("Script candidate read exceeds its configured limit")
        text, next_cursor, truncated = self._mirrors.read_candidate(
            job.mirror,
            path,
            cursor=cursor,
            max_chars=max_chars,
        )
        return {
            "execution_id": job.execution_id,
            "path": path,
            "cursor": cursor,
            "next_cursor": next_cursor,
            "text": text,
            "truncated": truncated,
            "job_state": job.state.value,
        }

    def apply(
        self,
        *,
        turn_id: str,
        execution_id: str,
    ) -> ScriptJobApply:
        job = self._job(turn_id, execution_id)
        self._refresh(job)
        if job.state is not ScriptJobState.READY_TO_APPLY:
            raise ScriptStateError("Only a successful completed Script job can be applied")
        try:
            committed = self._mirrors.commit(
                job.mirror,
                owner_turn_id=turn_id,
            )
        except WorkspaceMirrorConflict:
            raise
        payload: JsonObject = {
            "execution_id": job.execution_id,
            "job_state": "applied",
            "source_link": job.source.link,
            "source_digest": job.source.digest,
            "source_snapshot_digest": job.source.snapshot_digest,
            "workspace_links": [
                item.workspace_link
                for item in committed.changes
                if item.change != "deleted"
            ],
            "deleted_links": [
                item.workspace_link
                for item in committed.changes
                if item.change == "deleted"
            ],
            "workspace_changes": [
                {"link": item.workspace_link, "change": item.change}
                for item in committed.changes
            ],
            "workspace_revision": committed.manifest.revision,
        }
        self._remove(job, suppress_cleanup=True)
        return ScriptJobApply(payload=payload, manifest=committed.manifest)

    def discard(self, *, turn_id: str, execution_id: str) -> JsonObject:
        job = self._job(turn_id, execution_id)
        self._refresh(job)
        if job.state is ScriptJobState.RUNNING:
            raise ScriptStateError("A running Script job must be stopped before discard")
        payload: JsonObject = {
            "execution_id": job.execution_id,
            "job_state": "discarded",
            "source_link": job.source.link,
            "source_digest": job.source.digest,
        }
        self._remove(job, suppress_cleanup=True)
        return payload

    def has_unresolved(self, turn_id: str) -> bool:
        with self._lock:
            return turn_id in self._by_turn

    def allow_supervision_cycle(self, turn_id: str) -> bool:
        with self._lock:
            execution_id = self._by_turn.get(turn_id)
            if execution_id is None:
                return False
            job = self._jobs[execution_id]
            self._refresh(job)
            if monotonic() >= job.deadline:
                return False
            if job.supervision_cycles >= self._settings.max_supervision_cycles:
                return False
            job.supervision_cycles += 1
            return True

    def allow_additional_cycle(self, turn_id: str) -> bool:
        """Grant one bounded Cycle beyond the ordinary Turn limit."""

        return self.allow_supervision_cycle(turn_id)

    def wait_before_cycle(self, turn_id: str, *, bus: SignalBus) -> None:
        """Pace adjacent Cycles while the Turn owns a running process."""

        try:
            with self._lock:
                execution_id = self._by_turn.get(turn_id)
                job = self._jobs.get(execution_id) if execution_id else None
            if job is None:
                return
            while True:
                self._refresh(job)
                if job.state is not ScriptJobState.RUNNING:
                    return
                now = monotonic()
                remaining = job.next_cycle_at - now
                if remaining <= 0:
                    job.next_cycle_at = now + self._settings.cycle_wait_seconds
                    return
                matched = job.signal_watch.wait_for_matching(
                    lambda signal: _is_turn_wake_signal(signal, turn_id),
                    min(0.1, remaining),
                )
                if matched is not None:
                    job.next_cycle_at = monotonic() + self._settings.cycle_wait_seconds
                    return
        except RuntimeException:
            raise
        except Exception as exc:
            if self._runtime_bridge is None:
                raise
            raise self._runtime_bridge.from_script_error(
                exc,
                payload={"turn_id": turn_id, "operation": "wait_before_cycle"},
            ) from exc

    def cleanup_turn(self, turn_id: str) -> None:
        with self._lock:
            execution_id = self._by_turn.get(turn_id)
            job = self._jobs.get(execution_id) if execution_id else None
        if job is None:
            return
        try:
            if job.process.running():
                job.process.terminate()
                job.process.wait(5.0)
        except Exception:
            pass
        finally:
            self._remove(job, suppress_cleanup=True)

    def cleanup_all(self) -> None:
        with self._lock:
            turn_ids = tuple(self._by_turn)
        for turn_id in turn_ids:
            self.cleanup_turn(turn_id)

    def _wait_job(
        self,
        job: _ScriptJob,
        *,
        wait_seconds: int,
        control: ActionExecutionControl,
        bus: SignalBus | None,
    ) -> ScriptJobObservation:
        wait_deadline = monotonic() + wait_seconds
        while True:
            self._refresh(job)
            if job.state is not ScriptJobState.RUNNING:
                return self._observation(job)
            if control.is_cancelled() or control.is_expired():
                job.process.terminate()
                job.process.wait(5.0)
                job.state = ScriptJobState.TIMED_OUT
                job.failure_reason = control.cancel_reason or "action_cancelled"
                return self._observation(job)
            remaining = wait_deadline - monotonic()
            if remaining <= 0:
                return self._observation(job)
            slice_seconds = min(0.1, remaining)
            if bus is None:
                job.process.wait(slice_seconds)
                continue
            matched = job.signal_watch.wait_for_matching(
                lambda signal: _is_turn_wake_signal(signal, job.turn_id),
                slice_seconds,
            )
            if matched is not None:
                job.next_cycle_at = monotonic()
                return self._observation(job)

    def _refresh(self, job: _ScriptJob) -> None:
        if job.state is not ScriptJobState.RUNNING:
            return
        stdout_bytes, stderr_bytes = job.process.output_sizes()
        if max(stdout_bytes, stderr_bytes) > self._settings.max_log_bytes:
            job.process.terminate()
            job.process.wait(5.0)
            job.state = ScriptJobState.FAILED
            job.failure_reason = "log_bytes_limit_exceeded"
            return
        if monotonic() >= job.deadline:
            job.process.terminate()
            job.process.wait(5.0)
            job.state = ScriptJobState.TIMED_OUT
            job.failure_reason = "runtime_limit_exceeded"
            return
        exit_code = job.process.exit_code
        if exit_code is None:
            return
        if exit_code == 0:
            job.state = ScriptJobState.READY_TO_APPLY
        else:
            job.state = ScriptJobState.FAILED
            job.failure_reason = "process_exit_nonzero"

    def _observation(self, job: _ScriptJob) -> ScriptJobObservation:
        self._refresh(job)
        stdout = job.process.read_stdout(
            cursor=job.stdout_cursor,
            max_chars=self._settings.max_log_delta_chars,
            max_bytes=self._settings.max_log_bytes,
        )
        stderr = job.process.read_stderr(
            cursor=job.stderr_cursor,
            max_chars=self._settings.max_log_delta_chars,
            max_bytes=self._settings.max_log_bytes,
        )
        job.stdout_cursor = stdout.next_cursor
        job.stderr_cursor = stderr.next_cursor
        diff = self._mirrors.diff(job.mirror)
        candidates = diff.candidates[: self._settings.max_candidates]
        payload: JsonObject = {
            "execution_id": job.execution_id,
            "job_state": job.state.value,
            "source_link": job.source.link,
            "source_digest": job.source.digest,
            "language": job.source.language.value,
            "elapsed_seconds": max(0.0, monotonic() - job.started_at),
            "exit_code": job.process.exit_code,
            "failure_reason": job.failure_reason,
            "stdout": {
                "cursor": stdout.cursor,
                "next_cursor": stdout.next_cursor,
                "text": stdout.text,
                "truncated": stdout.truncated,
            },
            "stderr": {
                "cursor": stderr.cursor,
                "next_cursor": stderr.next_cursor,
                "text": stderr.text,
                "truncated": stderr.truncated,
            },
            "candidates": [
                {
                    "path": item.path,
                    "change": item.change,
                    "size": item.size,
                    "digest": item.digest,
                }
                for item in candidates
            ],
            "candidate_count": len(diff.candidates),
            "candidates_truncated": len(diff.candidates) > len(candidates),
        }
        return ScriptJobObservation(
            payload=payload,
            timed_out=job.state is ScriptJobState.TIMED_OUT,
            failed=job.state is ScriptJobState.FAILED,
        )

    def _job(self, turn_id: str, execution_id: str) -> _ScriptJob:
        if not turn_id:
            raise ScriptContractError("Script job operation requires a Turn id")
        with self._lock:
            effective_id = execution_id or self._by_turn.get(turn_id, "")
            job = self._jobs.get(effective_id)
            if job is None or job.turn_id != turn_id:
                raise ScriptStateError("Script execution id is not active in this Turn")
            return job

    def _remove(self, job: _ScriptJob, *, suppress_cleanup: bool = False) -> None:
        first_error: Exception | None = None
        job.signal_watch.close()
        try:
            job.process.close()
        except Exception as exc:
            first_error = exc
        try:
            self._staging.cleanup(job.staging_root)
        except Exception as exc:
            first_error = first_error or exc
        finally:
            with self._lock:
                self._jobs.pop(job.execution_id, None)
                if self._by_turn.get(job.turn_id) == job.execution_id:
                    self._by_turn.pop(job.turn_id, None)
        if first_error is not None and not suppress_cleanup:
            raise ScriptExecutionError("Script job cleanup failed") from first_error

    def _execution_source(
        self,
        source: ScriptSource,
        staging_root: Path,
        mirror: WorkspaceMirror,
    ) -> Path:
        del mirror
        source_root = staging_root / "source"
        source_root.mkdir()
        entry = source_root / f"entry{source.language.suffix}"
        entry.write_bytes(source.text.encode("utf-8"))
        return entry

    def _argv(
        self,
        language: ScriptLanguage,
        script_path: Path,
        args: tuple[str, ...],
    ) -> tuple[str, ...]:
        if language is ScriptLanguage.PYTHON:
            executable = sys.executable
        else:
            executable = self._settings.bash.executable or "bash"
        return executable, str(script_path), *args

    @staticmethod
    def _environment(workspace_root: Path) -> dict[str, str]:
        allowed = ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH", "HOME", "USERPROFILE")
        env = {name: os.environ[name] for name in allowed if name in os.environ}
        env.update(
            {
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUNBUFFERED": "1",
                "TINYSOUL_WORKSPACE": str(workspace_root),
            }
        )
        return env


def _is_turn_wake_signal(signal: Signal, turn_id: str) -> bool:
    frame = signal.scope.nearest(RunLevel.TURN)
    if frame is None or frame.name != turn_id:
        return False
    try:
        if signal.name == SIGNAL_INPUT_APPEND:
            return bool(parse_input_append_signal(signal))
        if signal.name == SIGNAL_CONTROL_REQUEST:
            request = parse_control_request_signal(signal)
            return request.kind in {
                LoopControlKind.STOP_TURN,
                LoopControlKind.EXIT_PROGRAM,
            }
    except (ContextError, LoopError):
        return False
    return False
