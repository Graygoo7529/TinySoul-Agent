"""One ACP prompt is one Turn-owned Job; the Registry owns its lifecycle."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import uuid4

from tinysoul.infra.concurrency import CleanupDiagnostic, JoinedOperations
from tinysoul.infra.json import JsonObject
from tinysoul.kernel.jobs import (
    JobInputOption,
    JobInputRequest,
    JobSnapshot,
    JobState,
    JobError,
)
from tinysoul.plugins.workspace import WorkspaceError
from tinysoul.plugins.workspace.services import WorkspaceExecutionPort
from tinysoul.plugins.workspace.inspection.models import WorkspaceBundleWrite
from tinysoul.plugins.workspace.runtime_bridge import RuntimeWorkspaceBridge
from ..acp.connection import ACPConnection
from ..config import SubagentSettings
from ..failures import SubagentFailure, SubagentRequestError


@dataclass
class _Pending:
    request: JobInputRequest
    answer: asyncio.Future[str | None]


class ACPJobBackend:
    kind = "subagent.acp"

    def __init__(
        self,
        job_id: str,
        connection: ACPConnection,
        brief: str,
        *,
        settings: SubagentSettings,
        workspace: WorkspaceExecutionPort,
        closed: Callable[[], Awaitable[None]],
    ) -> None:
        self.job_id = job_id
        self._connection, self._settings, self._workspace = (
            connection,
            settings,
            workspace,
        )
        self._closed_callback = closed
        self._pending: dict[str, _Pending] = {}
        self._output: list[str] = []
        self._chars = 0
        self._saved_chars = -1
        self._write_lock = asyncio.Lock()
        self._state = JobState.RUNNING
        self._reason = ""
        self._closed = False
        self._output_overflow = False
        self._link = f"workspace:jobs/{job_id}/output.txt"
        self._task = asyncio.create_task(self._run(brief))

    async def _run(self, brief: str) -> None:
        try:
            async with asyncio.timeout(self._settings.max_runtime_seconds):
                reason = await self._connection.prompt(brief, self)
            self._reason = reason
            self._state = (
                JobState.SUCCEEDED
                if reason == "end_turn"
                else JobState.CANCELLED
                if reason == "cancelled"
                else JobState.FAILED
            )
        except TimeoutError:
            await self._connection.close()
            self._state, self._reason = JobState.FAILED, "timeout"
        except asyncio.CancelledError:
            if self._output_overflow:
                await self._connection.close()
                self._state, self._reason = JobState.FAILED, "output_limit"
            else:
                self._state, self._reason = JobState.CANCELLED, "cancelled"
                raise
        except Exception:
            await self._connection.close()
            self._state, self._reason = JobState.FAILED, "external_failure"
        finally:
            self._cancel_inputs()

    async def text(self, text: str) -> None:
        if self._chars + len(text) > self._settings.max_output_chars:
            # Stop the producer; do not silently present a partial output as complete.
            self._output_overflow = True
            self._task.cancel()
            return
        self._output.append(text)
        self._chars += len(text)

    async def permission(
        self, question: str, options: tuple[tuple[str, str], ...]
    ) -> str | None:
        if len(self._pending) >= 4 or self._state.terminal:
            return None
        identity = f"request_{uuid4().hex}"
        try:
            request = JobInputRequest(
                identity,
                question,
                tuple(JobInputOption(key, label[:256]) for key, label in options),
            )
        except JobError:
            return None
        future: asyncio.Future[str | None] = asyncio.get_running_loop().create_future()
        self._pending[identity] = _Pending(request, future)
        try:
            return await future
        finally:
            self._pending.pop(identity, None)

    def respond(self, request_id: str, option_id: str) -> None:
        pending = self._pending.get(request_id)
        if (
            pending is None
            or pending.answer.done()
            or option_id not in {option.option_id for option in pending.request.options}
        ):
            raise SubagentRequestError(
                SubagentFailure.INVALID_REQUEST,
                "Permission request or option is no longer available.",
            )
        pending.answer.set_result(option_id)

    def _cancel_inputs(self) -> None:
        for pending in self._pending.values():
            if not pending.answer.done():
                pending.answer.set_result(None)

    async def poll(self) -> JobSnapshot:
        if self._task.done() and not self._task.cancelled():
            self._task.result()
        if self._state.terminal:
            await self._flush()
        pending = tuple(
            item.request for item in self._pending.values() if not item.answer.done()
        )
        state = JobState.WAITING_INPUT if pending else self._state
        return JobSnapshot(
            self.job_id,
            self.kind,
            state,
            "External Agent delegation.",
            self._reason,
            pending,
            (self._link,) if self._saved_chars >= 0 else (),
        )

    async def request_stop(self) -> None:
        self._cancel_inputs()
        if not self._task.done():
            try:
                async with asyncio.timeout(self._settings.stop_timeout_seconds):
                    await self._connection.cancel()
                    await asyncio.shield(self._task)
            except Exception:
                await self._connection.close()
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
                # Closing the transport can interrupt the prompt's own error
                # cleanup. The process tree is now stopped and the task joined.
                if not self._state.terminal:
                    self._state, self._reason = JobState.CANCELLED, "cancelled"

    async def close_execution(self) -> tuple[CleanupDiagnostic, ...]:
        if not self._closed:
            if (
                self._task.done()
                and not self._task.cancelled()
                and self._task.exception() is not None
            ):
                await self._connection.close()
                self._state, self._reason = JobState.FAILED, "external_failure"
            await self.request_stop()
            await self._connection.close_execution()
            self._closed = True
            await self._closed_callback()
        return ()

    async def _flush(self) -> None:
        async with self._write_lock:
            if self._saved_chars == self._chars:
                return
            count, text = self._chars, "".join(self._output)
            operation = JoinedOperations()
            try:
                await operation.run(
                    lambda: self._workspace.write_bundle(
                        (
                            WorkspaceBundleWrite(
                                self._link, text.encode(), overwrite=True
                            ),
                        )
                    )
                )
            except WorkspaceError as exc:
                raise RuntimeWorkspaceBridge().from_workspace_error(exc) from exc
            self._saved_chars = count
            operation.check_cancelled()

    async def collect(self, cursor: int = 0) -> JsonObject:
        if type(cursor) is not int or cursor < 0 or cursor > self._chars:
            raise SubagentRequestError(
                SubagentFailure.INVALID_REQUEST, "Output cursor is unavailable."
            )
        await self._flush()
        text = "".join(self._output)
        end = min(len(text), cursor + self._settings.max_collect_chars)
        return {
            "job_id": self.job_id,
            "text": text[cursor:end],
            "next_cursor": end,
            "truncated": end < len(text),
            "result_link": self._link,
        }

    async def describe(self) -> JsonObject:
        return {
            "output_chars": self._chars,
            "result_links": [self._link] if self._saved_chars >= 0 else [],
        }

    async def cleanup(self) -> tuple[CleanupDiagnostic, ...]:
        await self._flush()
        return ()
