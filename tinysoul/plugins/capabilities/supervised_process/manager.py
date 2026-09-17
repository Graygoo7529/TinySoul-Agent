"""Turn-scoped supervised process jobs shared by Script and Shell."""

from __future__ import annotations

import asyncio

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from time import monotonic

from tinysoul.kernel.action import ActionExecutionControl
from tinysoul.kernel.action.backends import (
    ManagedProcess,
    ManagedProcessRequest,
    ManagedProcessRunner,
    ManagedProcessStartError,
)
from tinysoul.infra import JsonObject, StagingDirectoryManager
from tinysoul.infra.concurrency import JoinedOperations
from tinysoul.kernel.jobs import JobError, JobRegistry, JobSnapshot, JobState
from tinysoul.kernel.loop.inbox import TurnInbox
from tinysoul.infra.concurrency import CleanupDiagnostic
from tinysoul.runtime import RunScope
from tinysoul.runtime import SignalBus
from tinysoul.plugins.workspace import (
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
)


_RESERVED_IDENTITY_KEYS = {
    "execution_id",
    "job_id",
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
    auto_complete_without_changes: bool
    controller: SupervisedProcessManager
    stdout_cursor: int = 0
    stderr_cursor: int = 0
    state: SupervisedProcessState = SupervisedProcessState.RUNNING
    failure_reason: str = ""
    observation_index: int = 0
    observed_stdout_bytes: int = 0
    observed_stderr_bytes: int = 0
    observed_candidate_count: int = 0
    observed_candidate_signature: tuple[tuple[str, str, int, str], ...] = ()
    last_observed_activity_at: float = 0.0

    def poll(self) -> JobSnapshot:
        with self.controller._lock:
            self.controller._refresh(self)
            state = {
                SupervisedProcessState.RUNNING: JobState.RUNNING,
                SupervisedProcessState.COMPLETED: JobState.SUCCEEDED,
                SupervisedProcessState.READY_TO_APPLY: JobState.SUCCEEDED,
                SupervisedProcessState.FAILED: JobState.FAILED,
                SupervisedProcessState.TIMED_OUT: JobState.TIMED_OUT,
                SupervisedProcessState.STOPPED: JobState.STOPPED,
            }[self.state]
            return JobSnapshot(self.execution_id, self.owner.value, state,
                               self.failure_reason or self.state.value)

    def request_stop(self) -> None:
        self.controller.stop(turn_id=self.turn_id, execution_id=self.execution_id)

    def describe(self) -> JsonObject:
        with self.controller._lock:
            return self.controller._observation(self).payload

    def close_execution(self) -> None:
        with self.controller._lock:
            self.process.close()

    def cleanup(self) -> None:
        with self.controller._lock:
            self.controller._remove(self)


class SupervisedProcessManager:
    """Own at most one unresolved Script or Shell job per active Turn."""

    def __init__(
        self,
        *,
        settings: SupervisedProcessSettings,
        mirror_service: WorkspaceMirrorService,
        staging: StagingDirectoryManager,
        process_runner: ManagedProcessRunner | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._settings = settings
        self._mirrors = mirror_service
        self._staging = staging
        self._process_runner = process_runner or ManagedProcessRunner()
        self._clock = clock
        self._registry = JobRegistry[_ProcessJob](per_turn_capacity=1)
        self._lock = RLock()

    @property
    def registry(self) -> JobRegistry[_ProcessJob]:
        return self._registry

    @property
    def settings(self) -> SupervisedProcessSettings:
        return self._settings

    async def start(
        self,
        *,
        turn_id: str,
        owner: SupervisedProcessOwner,
        identity: JsonObject,
        prepare: SupervisedProcessPreparer,
        control: ActionExecutionControl,
        auto_complete_without_changes: bool = False,
    ) -> SupervisedProcessObservation:
        control.check_cancelled()
        if not isinstance(owner, SupervisedProcessOwner):
            raise SupervisedProcessContractError("Process owner must be a supported capability")
        for previous_id in self._registry.ids(turn_id):
            previous = self._registry.get(turn_id, previous_id)
            if previous.state is SupervisedProcessState.COMPLETED:
                await self._registry.release(turn_id, previous_id)
        try:
            job = await self._registry.start(turn_id, owner.value, lambda execution_id: self._start(
                turn_id=turn_id, owner=owner, identity=identity, prepare=prepare,
                auto_complete_without_changes=auto_complete_without_changes,
                execution_id=execution_id,
            ))
        except JobError as exc:
            raise SupervisedProcessStateError("Turn cannot accept another process Job") from exc
        operations = JoinedOperations()
        try:
            result = await operations.run(lambda: self._observation(job))
            operations.check_cancelled()
            return result
        except asyncio.CancelledError:
            await self.cleanup_turn(turn_id)
            raise

    def _start(
        self, *, turn_id: str, owner: SupervisedProcessOwner, identity: JsonObject,
        prepare: SupervisedProcessPreparer,
        auto_complete_without_changes: bool,
        execution_id: str,
    ) -> _ProcessJob:
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
        with self._lock:
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
                auto_complete_without_changes=auto_complete_without_changes,
                controller=self,
                last_observed_activity_at=now,
            )
        return job

    def stop(
        self,
        *,
        turn_id: str,
        execution_id: str,
    ) -> None:
        # Polling runs on another owner worker. Keep termination and its cause
        # in one transition so the monitor cannot classify our exit as failure.
        with self._lock:
            job = self._job(turn_id, execution_id)
            self._refresh_locked(job)
            if job.state is SupervisedProcessState.RUNNING:
                self._terminate(job)
                job.state = SupervisedProcessState.STOPPED
                job.failure_reason = "stopped_by_agent"

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

    async def apply(
        self, *, turn_id: str, execution_id: str,
        operations: JoinedOperations | None = None,
    ) -> SupervisedProcessApply:
        joined = operations or JoinedOperations()
        result = await joined.run(lambda: self._apply(turn_id=turn_id, execution_id=execution_id))
        # Commit and resource release are one action boundary. Defer a caller's
        # cancellation until its execution-fact recorder has seen the commit.
        await joined.finish(lambda: self._registry.release(turn_id, execution_id))
        return result

    def _apply(
        self,
        *,
        turn_id: str,
        execution_id: str,
    ) -> SupervisedProcessApply:
        job = self._job(turn_id, execution_id)
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
        return SupervisedProcessApply(payload=payload, manifest=committed.manifest)

    async def discard(
        self, *, turn_id: str, execution_id: str,
        operations: JoinedOperations | None = None,
    ) -> JsonObject:
        joined = operations or JoinedOperations()
        result = await joined.run(lambda: self._discard(turn_id=turn_id, execution_id=execution_id))
        await joined.finish(lambda: self._registry.release(turn_id, execution_id))
        return result

    def _discard(
        self,
        *,
        turn_id: str,
        execution_id: str,
    ) -> JsonObject:
        job = self._job(turn_id, execution_id)
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
        return payload

    def has_unresolved(self, turn_id: str) -> bool:
        return any(self._registry.get(turn_id, job_id).state is not SupervisedProcessState.COMPLETED
                   for job_id in self._registry.ids(turn_id))

    def bind_inbox(self, turn_id: str, inbox: TurnInbox | None) -> None:
        self._registry.bind_inbox(turn_id, inbox)

    def sync(self, turn_id: str, *, bus: SignalBus, scope: RunScope) -> None:
        self._registry.sync(turn_id, bus=bus, scope=scope)

    async def cleanup_turn(self, turn_id: str) -> tuple[CleanupDiagnostic, ...]:
        return await self._registry.cleanup_turn(turn_id)

    def _refresh(self, job: _ProcessJob) -> None:
        with self._lock:
            self._refresh_locked(job)

    def _refresh_locked(self, job: _ProcessJob) -> None:
        if job.state is not SupervisedProcessState.RUNNING:
            return
        stdout_bytes, stderr_bytes = job.process.output_sizes()
        if max(stdout_bytes, stderr_bytes) > self._settings.max_log_bytes:
            self._terminate(job)
            job.state = SupervisedProcessState.FAILED
            job.failure_reason = "log_bytes_limit_exceeded"
            return
        if self._clock() >= job.deadline:
            self._terminate(job)
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

    def _observation(self, job: _ProcessJob) -> SupervisedProcessObservation:
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
            "job_id": job.execution_id,
            "owner": job.owner.value,
            "job_state": job.state.value,
            "elapsed_seconds": max(0.0, now - job.started_at),
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
        execution_id: str,
    ) -> _ProcessJob:
        if not turn_id:
            raise SupervisedProcessContractError(
                "Process job operation requires a Turn id"
            )
        with self._lock:
            try:
                return self._registry.get(turn_id, execution_id)
            except JobError as exc:
                raise SupervisedProcessStateError(
                    "Execution id is not active in this Turn"
                ) from exc

    @staticmethod
    def _terminate(job: _ProcessJob) -> None:
        job.process.terminate()
        if job.process.running():
            raise SupervisedProcessExecutionError(
                "Supervised process did not terminate after hard-stop request"
            )

    def _remove(self, job: _ProcessJob) -> None:
        first_error: Exception | None = None
        try:
            job.process.close()
        except Exception as exc:
            first_error = first_error or exc
        try:
            self._staging.cleanup(job.staging_root)
        except Exception as exc:
            first_error = first_error or exc
        if first_error is not None:
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
