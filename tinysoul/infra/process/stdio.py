"""Async protocol pipes over the same platform process containment as commands."""

from __future__ import annotations

import asyncio
import os
import subprocess

from tinysoul.infra.concurrency import CleanupDiagnostic, JoinedOperations
from .managed import (
    ManagedProcessCloseError,
    ManagedProcessRequest,
    ManagedProcessStartError,
    ProcessContractError,
    ProcessScope,
)


class StdioProcess:
    """Own a protocol server and its descendants until explicit close."""

    def __init__(
        self, process: asyncio.subprocess.Process, scope: ProcessScope
    ) -> None:
        assert process.stdin is not None and process.stdout is not None
        self.stdin, self.stdout = process.stdin, process.stdout
        self._process, self._scope = process, scope
        self._closed = False
        self._lock = asyncio.Lock()
        self._stderr = asyncio.create_task(self._drain_stderr())

    @classmethod
    async def start(
        cls, request: ManagedProcessRequest, *, max_message_bytes: int = 8_000_000
    ) -> StdioProcess:
        if request.stdin_text is not None or max_message_bytes <= 0:
            raise ProcessContractError(
                "Protocol process requires bounded asynchronous pipes"
            )
        environment = dict(os.environ) if request.inherit_env else {}
        environment.update(request.env or {})

        async def launch() -> StdioProcess:
            scope: ProcessScope | None = None
            process: asyncio.subprocess.Process | None = None
            try:
                if os.name == "nt":
                    from .windows import WindowsProcessJob

                    scope = WindowsProcessJob()
                    process = await asyncio.create_subprocess_exec(
                        *request.argv,
                        cwd=request.cwd,
                        env=environment,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        limit=max_message_bytes,
                        creationflags=subprocess.CREATE_NO_WINDOW
                        | subprocess.CREATE_NEW_PROCESS_GROUP
                        | WindowsProcessJob.CREATE_SUSPENDED,
                    )
                    await JoinedOperations().run(lambda: scope.attach(process.pid))
                else:
                    from .managed import PosixProcessGroup

                    process = await asyncio.create_subprocess_exec(
                        *request.argv,
                        cwd=request.cwd,
                        env=environment,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        limit=max_message_bytes,
                        start_new_session=True,
                    )
                    scope = PosixProcessGroup(process.pid)
                return cls(process, scope)
            except Exception as exc:
                if process is not None:
                    process.kill()
                    await process.wait()
                if scope is not None:
                    scope.close()
                raise ManagedProcessStartError(
                    "Protocol process could not start"
                ) from exc

        joined = JoinedOperations()
        result = await joined.run_async(launch)
        if joined.cancelled:
            await result.close()
            joined.check_cancelled()
        return result

    async def _drain_stderr(self) -> None:
        # Diagnostics cannot block the protocol or grow a second unbounded log.
        assert self._process.stderr is not None
        while await self._process.stderr.read(65536):
            pass

    async def close(self) -> tuple[CleanupDiagnostic, ...]:
        async def finish() -> tuple[CleanupDiagnostic, ...]:
            async with self._lock:
                if self._closed:
                    return ()
                try:
                    await JoinedOperations().run(lambda: self._scope.terminate(2.0))
                    await asyncio.wait_for(self._process.wait(), 3.0)
                except (OSError, TimeoutError) as exc:
                    raise ManagedProcessCloseError(
                        "Protocol process tree could not stop"
                    ) from exc
                diagnostics: list[CleanupDiagnostic] = []
                try:
                    self._scope.close()
                    self.stdin.close()
                    await self.stdin.wait_closed()
                except (OSError, ConnectionError) as exc:
                    diagnostics.append(
                        CleanupDiagnostic("process.stdio", type(exc).__name__)
                    )
                await self._stderr
                self._closed = True
                return tuple(diagnostics)

        joined = JoinedOperations()
        result = await joined.run_async(finish)
        joined.check_cancelled()
        return result
