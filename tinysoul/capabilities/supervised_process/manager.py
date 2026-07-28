"""Turn-scoped supervised process jobs shared by Script and Shell."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import NoReturn, Protocol
from uuid import uuid4

from tinysoul.action import ActionExecutionControl
from tinysoul.action.backends import (
    ManagedProcess,
    ManagedProcessRequest,
    ManagedProcessRunner,
    ManagedProcessStartError,
)
from tinysoul.context import (
    SIGNAL_INPUT_APPEND,
    ContextError,
    parse_input_append_signal,
)
from tinysoul.infra import JsonObject, StagingDirectoryManager
from tinysoul.loop import LoopError
from tinysoul.loop.signals import (
    SIGNAL_CONTROL_REQUEST,
    LoopControlKind,
    parse_control_request_signal,
)
from tinysoul.runtime import (
    RunLevel,
    RuntimeException,
    Signal,
    SignalBus,
    SignalWatch,
)
from tinysoul.workspace import (
    WorkspaceMirror,
    WorkspaceMirrorConflict,
    WorkspaceMirrorService,
)

from .config import SupervisedProcessSettings
from .errors import (
    SupervisedProcessContractError,
    SupervisedProcessExecutionError,
    SupervisedProcessStateError,
)
from .models import (
    SupervisedProcessApply,
    SupervisedProcessObservation,
    SupervisedProcessOwner,
    SupervisedProcessPreparer,
    SupervisedProcessState,
    SupervisedProcessWakeReason,
)


_RESERVED_IDENTITY_KEYS = {
    "execution_id",
    "owner",
    "job_state",
    "elapsed_seconds",
    "exit_code",
    "failure_reason",
    "stdout",
    "stderr",
    "candidates",
    "candidate_count",
    "candidates_truncated",
    "workspace_links",
    "deleted_links",
    "workspace_changes",
    "workspace_revision",
    "wake_reason",
    "requested_wait_seconds",
    "actual_wait_seconds",
    "remaining_runtime_seconds",
    "observed_activity",
}


@dataclass
class _ProcessJob:
    execution_id: str
    turn_id: str
    owner: SupervisedProcessOwner
    identity: JsonObject
    staging_root: Path
    mirror: WorkspaceMirror
    process: ManagedProcess
    started_at: float
    deadline: float
    signal_watch: SignalWatch
    auto_complete_without_changes: bool
    stdout_cursor: int = 0
    stderr_cursor: int = 0
    state: SupervisedProcessState = SupervisedProcessState.RUNNING
    failure_reason: str = ""
    supervision_cycles: int = 0
    next_cycle_at: float = 0.0
    observation_index: int = 0
    observed_stdout_bytes: int = 0
    observed_stderr_bytes: int = 0
    observed_candidate_count: int = 0
    observed_candidate_signature: tuple[tuple[str, str, int, str], ...] = ()
    last_observed_activity_at: float = 0.0


class SupervisedProcessRuntimeBridge(Protocol):
    def from_supervised_process_error(
        self,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException: ...


class SupervisedProcessManager:
    """Own at most one unresolved Script or Shell job per active Turn."""

    def __init__(
        self,
        *,
        settings: SupervisedProcessSettings,
        mirror_service: WorkspaceMirrorService,
        staging: StagingDirectoryManager,
        process_runner: ManagedProcessRunner | None = None,
        runtime_bridge: SupervisedProcessRuntimeBridge | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._settings = settings
        self._mirrors = mirror_service
        self._staging = staging
        self._process_runner = process_runner or ManagedProcessRunner()
        self._runtime_bridge = runtime_bridge
        self._clock = clock
        self._jobs: dict[str, _ProcessJob] = {}
        self._by_turn: dict[str, str] = {}
        self._lock = RLock()

    @property
    def settings(self) -> SupervisedProcessSettings:
        return self._settings

    def start(
        self,
        *,
        turn_id: str,
        owner: SupervisedProcessOwner,
        identity: JsonObject,
        prepare: SupervisedProcessPreparer,
        control: ActionExecutionControl,
        bus: SignalBus | None,
        auto_complete_without_changes: bool = False,
    ) -> SupervisedProcessObservation:
        if not turn_id:
            raise SupervisedProcessContractError(
                "Supervised process run requires a Turn id"
            )
        if not isinstance(owner, SupervisedProcessOwner):
            raise SupervisedProcessContractError(
                "Supervised process owner must be a supported capability"
            )
        if not isinstance(identity, dict):
            raise SupervisedProcessContractError(
                "Supervised process identity must be a JSON object"
            )
        conflicts = _RESERVED_IDENTITY_KEYS.intersection(identity)
        if conflicts:
            raise SupervisedProcessContractError(
                "Supervised process identity uses reserved fields: "
                + ", ".join(sorted(conflicts))
            )
        signal_watch = bus.watch() if bus is not None else SignalBus().watch()
        with self._lock:
            if turn_id in self._by_turn:
                _close_watch(signal_watch)
                raise SupervisedProcessStateError(
                    "The current Turn already has an unresolved process job"
                )
            execution_id = f"process_{uuid4().hex}"
            staging_root: Path | None = None
            try:
                staging_root = self._staging.create("supervised-process-job")
                mirror = self._mirrors.create(staging_root / "workspace")
                request = prepare(staging_root, mirror)
                self._validate_request(request, mirror)
                process = self._process_runner.start(
                    request,
                    capture_root=staging_root / "logs",
                )
            except Exception as exc:
                _close_watch(signal_watch)
                if staging_root is not None:
                    try:
                        self._staging.cleanup(staging_root)
                    except Exception:
                        pass
                if not isinstance(exc, (OSError, ManagedProcessStartError)):
                    raise
                raise SupervisedProcessExecutionError(
                    "Supervised process could not be started"
                ) from exc
            now = self._clock()
            job = _ProcessJob(
                execution_id=execution_id,
                turn_id=turn_id,
                owner=owner,
                identity=dict(identity),
                staging_root=staging_root,
                mirror=mirror,
                process=process,
                started_at=now,
                deadline=now + self._settings.max_runtime_seconds,
                signal_watch=signal_watch,
                auto_complete_without_changes=auto_complete_without_changes,
                next_cycle_at=now + self._settings.cycle_wait_seconds,
                last_observed_activity_at=now,
            )
            self._jobs[execution_id] = job
            self._by_turn[turn_id] = execution_id
        return self._wait_job(
            job,
            wait_seconds=self._settings.initial_wait_seconds,
            control=control,
            bus=bus,
            interval_reason=SupervisedProcessWakeReason.INITIAL_INTERVAL_ELAPSED,
            release_next_cycle_on_interval=False,
        )

    def wait(
        self,
        *,
        turn_id: str,
        owner: SupervisedProcessOwner,
        execution_id: str,
        wait_seconds: int,
        control: ActionExecutionControl,
        bus: SignalBus | None,
    ) -> SupervisedProcessObservation:
        job = self._job(turn_id, owner, execution_id)
        if job.state is not SupervisedProcessState.RUNNING:
            return self._observation_and_finalize(
                job,
                wake_reason=SupervisedProcessWakeReason.ALREADY_RESOLVED,
                requested_wait_seconds=wait_seconds,
                actual_wait_seconds=0.0,
            )
        if not (
            self._settings.min_wait_seconds
            <= wait_seconds
            <= self._settings.max_wait_seconds
        ):
            raise SupervisedProcessContractError(
                "wait_seconds is outside the configured process boundaries"
            )
        return self._wait_job(
            job,
            wait_seconds=wait_seconds,
            control=control,
            bus=bus,
            interval_reason=SupervisedProcessWakeReason.REQUESTED_INTERVAL_ELAPSED,
            release_next_cycle_on_interval=True,
        )

    def stop(
        self,
        *,
        turn_id: str,
        owner: SupervisedProcessOwner,
        execution_id: str,
    ) -> SupervisedProcessObservation:
        job = self._job(turn_id, owner, execution_id)
        self._refresh(job)
        if job.state is SupervisedProcessState.RUNNING:
            job.process.terminate()
            job.process.wait(5.0)
            job.state = SupervisedProcessState.STOPPED
            job.failure_reason = "stopped_by_agent"
        return self._observation_and_finalize(
            job,
            wake_reason=SupervisedProcessWakeReason.AGENT_STOPPED,
            requested_wait_seconds=0,
            actual_wait_seconds=0.0,
        )

    def read_candidate(
        self,
        *,
        turn_id: str,
        owner: SupervisedProcessOwner,
        execution_id: str,
        path: str,
        cursor: int,
        max_chars: int,
    ) -> JsonObject:
        job = self._job(turn_id, owner, execution_id)
        if max_chars > self._settings.max_candidate_read_chars:
            raise SupervisedProcessContractError(
                "Candidate read exceeds its configured limit"
            )
        text, next_cursor, truncated = self._mirrors.read_candidate(
            job.mirror,
            path,
            cursor=cursor,
            max_chars=max_chars,
        )
        return {
            "execution_id": job.execution_id,
            "owner": job.owner.value,
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
        owner: SupervisedProcessOwner,
        execution_id: str,
    ) -> SupervisedProcessApply:
        job = self._job(turn_id, owner, execution_id)
        self._refresh(job)
        if job.state is not SupervisedProcessState.READY_TO_APPLY:
            raise SupervisedProcessStateError(
                "Only a successful process job with changes can be applied"
            )
        try:
            committed = self._mirrors.commit(job.mirror, owner_turn_id=turn_id)
        except WorkspaceMirrorConflict:
            raise
        payload: JsonObject = {
            **job.identity,
            "execution_id": job.execution_id,
            "owner": job.owner.value,
            "job_state": "applied",
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
        return SupervisedProcessApply(payload=payload, manifest=committed.manifest)

    def discard(
        self,
        *,
        turn_id: str,
        owner: SupervisedProcessOwner,
        execution_id: str,
    ) -> JsonObject:
        job = self._job(turn_id, owner, execution_id)
        self._refresh(job)
        if job.state is SupervisedProcessState.RUNNING:
            raise SupervisedProcessStateError(
                "A running process job must be stopped before discard"
            )
        payload: JsonObject = {
            **job.identity,
            "execution_id": job.execution_id,
            "owner": job.owner.value,
            "job_state": "discarded",
        }
        self._remove(job, suppress_cleanup=True)
        return payload

    def has_unresolved(self, turn_id: str) -> bool:
        with self._lock:
            return turn_id in self._by_turn

    def allow_additional_cycle(self, turn_id: str) -> bool:
        """Grant one bounded Cycle beyond the ordinary Turn limit."""

        try:
            with self._lock:
                execution_id = self._by_turn.get(turn_id)
                if execution_id is None:
                    return False
                job = self._jobs[execution_id]
                self._refresh(job)
                if job.supervision_cycles >= self._settings.max_supervision_cycles:
                    return False
                job.supervision_cycles += 1
                return True
        except RuntimeException:
            raise
        except Exception as exc:
            self._raise_runtime(
                exc,
                payload={"turn_id": turn_id, "operation": "allow_additional_cycle"},
            )

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
                if job.state is not SupervisedProcessState.RUNNING:
                    return
                now = self._clock()
                remaining = job.next_cycle_at - now
                if remaining <= 0:
                    job.next_cycle_at = now + self._settings.cycle_wait_seconds
                    return
                matched = job.signal_watch.wait_for_matching(
                    lambda signal: _is_turn_wake_signal(signal, turn_id),
                    min(0.1, remaining),
                )
                if matched is not None:
                    job.next_cycle_at = self._clock() + self._settings.cycle_wait_seconds
                    return
        except RuntimeException:
            raise
        except Exception as exc:
            self._raise_runtime(
                exc,
                payload={"turn_id": turn_id, "operation": "wait_before_cycle"},
            )

    def cleanup_turn(self, turn_id: str) -> None:
        with self._lock:
            execution_id = self._by_turn.get(turn_id)
            job = self._jobs.get(execution_id) if execution_id else None
        if job is None:
            return
        first_error: Exception | None = None
        try:
            if job.process.running():
                job.process.terminate()
                job.process.wait(5.0)
        except Exception as exc:
            first_error = exc
        try:
            self._remove(job)
        except Exception as exc:
            first_error = first_error or exc
        if first_error is not None:
            raise SupervisedProcessExecutionError(
                "Supervised process Turn cleanup failed"
            ) from first_error

    def cleanup_all(self) -> None:
        with self._lock:
            turn_ids = tuple(self._by_turn)
        for turn_id in turn_ids:
            self.cleanup_turn(turn_id)

    def _wait_job(
        self,
        job: _ProcessJob,
        *,
        wait_seconds: int,
        control: ActionExecutionControl,
        bus: SignalBus | None,
        interval_reason: SupervisedProcessWakeReason,
        release_next_cycle_on_interval: bool,
    ) -> SupervisedProcessObservation:
        wait_started = self._clock()
        wait_deadline = wait_started + wait_seconds
        while True:
            self._refresh(job)
            if job.state is not SupervisedProcessState.RUNNING:
                return self._observation_and_finalize(
                    job,
                    wake_reason=_terminal_wake_reason(job),
                    requested_wait_seconds=wait_seconds,
                    actual_wait_seconds=max(0.0, self._clock() - wait_started),
                )
            if control.is_cancelled() or control.is_expired():
                job.process.terminate()
                job.process.wait(5.0)
                job.state = SupervisedProcessState.TIMED_OUT
                job.failure_reason = control.cancel_reason or "action_cancelled"
                return self._observation_and_finalize(
                    job,
                    wake_reason=SupervisedProcessWakeReason.ACTION_CANCELLED,
                    requested_wait_seconds=wait_seconds,
                    actual_wait_seconds=max(0.0, self._clock() - wait_started),
                )
            remaining = wait_deadline - self._clock()
            if remaining <= 0:
                now = self._clock()
                if release_next_cycle_on_interval:
                    job.next_cycle_at = now
                return self._observation(
                    job,
                    wake_reason=interval_reason,
                    requested_wait_seconds=wait_seconds,
                    actual_wait_seconds=max(0.0, now - wait_started),
                )
            slice_seconds = min(0.1, remaining)
            if bus is None:
                job.process.wait(slice_seconds)
                continue
            matched = job.signal_watch.wait_for_matching(
                lambda signal: _turn_wake_reason(signal, job.turn_id) is not None,
                slice_seconds,
            )
            if matched is not None:
                job.next_cycle_at = self._clock()
                return self._observation(
                    job,
                    wake_reason=(
                        _turn_wake_reason(matched, job.turn_id)
                        or SupervisedProcessWakeReason.TURN_CONTROL
                    ),
                    requested_wait_seconds=wait_seconds,
                    actual_wait_seconds=max(0.0, self._clock() - wait_started),
                )

    def _refresh(self, job: _ProcessJob) -> None:
        if job.state is not SupervisedProcessState.RUNNING:
            return
        stdout_bytes, stderr_bytes = job.process.output_sizes()
        if max(stdout_bytes, stderr_bytes) > self._settings.max_log_bytes:
            job.process.terminate()
            job.process.wait(5.0)
            job.state = SupervisedProcessState.FAILED
            job.failure_reason = "log_bytes_limit_exceeded"
            return
        if self._clock() >= job.deadline:
            job.process.terminate()
            job.process.wait(5.0)
            job.state = SupervisedProcessState.TIMED_OUT
            job.failure_reason = "runtime_limit_exceeded"
            return
        exit_code = job.process.exit_code
        if exit_code is None:
            return
        if exit_code != 0:
            job.state = SupervisedProcessState.FAILED
            job.failure_reason = "process_exit_nonzero"
            return
        if job.auto_complete_without_changes and not self._mirrors.diff(
            job.mirror
        ).candidates:
            job.state = SupervisedProcessState.COMPLETED
        else:
            job.state = SupervisedProcessState.READY_TO_APPLY

    def _observation_and_finalize(
        self,
        job: _ProcessJob,
        *,
        wake_reason: SupervisedProcessWakeReason,
        requested_wait_seconds: int,
        actual_wait_seconds: float,
    ) -> SupervisedProcessObservation:
        observation = self._observation(
            job,
            wake_reason=wake_reason,
            requested_wait_seconds=requested_wait_seconds,
            actual_wait_seconds=actual_wait_seconds,
        )
        if job.state is SupervisedProcessState.COMPLETED:
            self._remove(job)
        return observation

    def _observation(
        self,
        job: _ProcessJob,
        *,
        wake_reason: SupervisedProcessWakeReason,
        requested_wait_seconds: int,
        actual_wait_seconds: float,
    ) -> SupervisedProcessObservation:
        self._refresh(job)
        now = self._clock()
        stdout_bytes, stderr_bytes = job.process.output_sizes()
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
        candidate_signature = tuple(
            (item.path, item.change, item.size, item.digest) for item in diff.candidates
        )
        stdout_bytes_delta = max(0, stdout_bytes - job.observed_stdout_bytes)
        stderr_bytes_delta = max(0, stderr_bytes - job.observed_stderr_bytes)
        candidate_count_delta = len(diff.candidates) - job.observed_candidate_count
        workspace_diff_changed = (
            candidate_signature != job.observed_candidate_signature
        )
        activity_since_last_observation = bool(
            stdout_bytes_delta or stderr_bytes_delta or workspace_diff_changed
        )
        if activity_since_last_observation:
            job.last_observed_activity_at = now
        job.observation_index += 1
        seconds_since_observed_activity = max(
            0.0,
            now - job.last_observed_activity_at,
        )
        job.observed_stdout_bytes = stdout_bytes
        job.observed_stderr_bytes = stderr_bytes
        job.observed_candidate_count = len(diff.candidates)
        job.observed_candidate_signature = candidate_signature
        payload: JsonObject = {
            **job.identity,
            "execution_id": job.execution_id,
            "owner": job.owner.value,
            "job_state": job.state.value,
            "elapsed_seconds": max(0.0, now - job.started_at),
            "wake_reason": wake_reason.value,
            "requested_wait_seconds": requested_wait_seconds,
            "actual_wait_seconds": max(0.0, actual_wait_seconds),
            "remaining_runtime_seconds": (
                max(0.0, job.deadline - now)
                if job.state is SupervisedProcessState.RUNNING
                else 0.0
            ),
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
            "observed_activity": {
                "observation_index": job.observation_index,
                "activity_since_last_observation": activity_since_last_observation,
                "stdout_bytes_delta": stdout_bytes_delta,
                "stderr_bytes_delta": stderr_bytes_delta,
                "workspace_diff_changed": workspace_diff_changed,
                "candidate_count_delta": candidate_count_delta,
                "seconds_since_observed_activity": seconds_since_observed_activity,
            },
        }
        return SupervisedProcessObservation(
            payload=payload,
            timed_out=job.state is SupervisedProcessState.TIMED_OUT,
            failed=job.state is SupervisedProcessState.FAILED,
        )

    def _job(
        self,
        turn_id: str,
        owner: SupervisedProcessOwner,
        execution_id: str,
    ) -> _ProcessJob:
        if not turn_id:
            raise SupervisedProcessContractError(
                "Process job operation requires a Turn id"
            )
        with self._lock:
            effective_id = execution_id or self._by_turn.get(turn_id, "")
            job = self._jobs.get(effective_id)
            if job is None or job.turn_id != turn_id:
                raise SupervisedProcessStateError(
                    "Execution id is not active in this Turn"
                )
            if job.owner is not owner:
                raise SupervisedProcessStateError(
                    "Execution id belongs to another capability"
                )
            return job

    def _remove(self, job: _ProcessJob, *, suppress_cleanup: bool = False) -> None:
        first_error: Exception | None = None
        try:
            job.signal_watch.close()
        except Exception as exc:
            first_error = exc
        try:
            job.process.close()
        except Exception as exc:
            first_error = first_error or exc
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
            raise SupervisedProcessExecutionError(
                "Supervised process job cleanup failed"
            ) from first_error

    @staticmethod
    def _validate_request(
        request: ManagedProcessRequest,
        mirror: WorkspaceMirror,
    ) -> None:
        if not isinstance(request, ManagedProcessRequest):
            raise SupervisedProcessContractError(
                "Process preparer must return ManagedProcessRequest"
            )
        if request.stdin_text is not None:
            raise SupervisedProcessContractError(
                "Supervised processes do not accept interactive stdin"
            )
        if request.cwd is None:
            raise SupervisedProcessContractError(
                "Supervised process cwd must be inside the Workspace mirror"
            )
        try:
            root = mirror.root.resolve()
            cwd = Path(request.cwd)
            if cwd.is_symlink() or not cwd.is_dir():
                raise SupervisedProcessContractError(
                    "Supervised process cwd must be an existing directory"
                )
            resolved = cwd.resolve()
        except OSError as exc:
            raise SupervisedProcessContractError(
                "Supervised process cwd could not be resolved"
            ) from exc
        if resolved != root and root not in resolved.parents:
            raise SupervisedProcessContractError(
                "Supervised process cwd must stay inside the Workspace mirror"
            )

    def _raise_runtime(self, error: Exception, *, payload: JsonObject) -> NoReturn:
        if self._runtime_bridge is None:
            raise error
        raise self._runtime_bridge.from_supervised_process_error(
            error,
            payload=payload,
        ) from error


def _close_watch(watch: SignalWatch) -> None:
    try:
        watch.close()
    except Exception:
        pass


def _turn_wake_reason(
    signal: Signal,
    turn_id: str,
) -> SupervisedProcessWakeReason | None:
    frame = signal.scope.nearest(RunLevel.TURN)
    if frame is None or frame.name != turn_id:
        return None
    try:
        if signal.name == SIGNAL_INPUT_APPEND:
            if parse_input_append_signal(signal):
                return SupervisedProcessWakeReason.USER_INPUT
        if signal.name == SIGNAL_CONTROL_REQUEST:
            request = parse_control_request_signal(signal)
            if request.kind in {
                LoopControlKind.STOP_TURN,
                LoopControlKind.EXIT_PROGRAM,
            }:
                return SupervisedProcessWakeReason.TURN_CONTROL
    except (ContextError, LoopError):
        return None
    return None


def _is_turn_wake_signal(signal: Signal, turn_id: str) -> bool:
    return _turn_wake_reason(signal, turn_id) is not None


def _terminal_wake_reason(job: _ProcessJob) -> SupervisedProcessWakeReason:
    if job.failure_reason == "runtime_limit_exceeded":
        return SupervisedProcessWakeReason.RUNTIME_LIMIT
    if job.state is SupervisedProcessState.TIMED_OUT:
        return SupervisedProcessWakeReason.ACTION_CANCELLED
    return SupervisedProcessWakeReason.PROCESS_EXITED
