"""Execution assembly facade: resolve requests and register real process backends."""

from __future__ import annotations

import asyncio
from base64 import b64encode
from pathlib import Path
import shutil

from tinysoul.infra.config import ConfigError
from tinysoul.infra.concurrency import JoinedOperations
from tinysoul.infra.process import (
    ManagedProcessRequest,
    ManagedProcessRunner,
    ManagedProcessStartError,
)
from tinysoul.kernel.jobs import JobRegistry
from tinysoul.plugins.home.services import HomeService
from tinysoul.plugins.workspace.services import WorkspaceExecutionPort

from .backend import ProcessJobBackend
from .config import ExecutionSettings, Interpreter
from .failures import ExecutionRequestError, ExecutionStartError


class ExecutionEngine:
    """No task store: all accepted executions belong to the injected JobRegistry."""

    def __init__(
        self,
        *,
        settings: ExecutionSettings,
        jobs: JobRegistry,
        workspace: WorkspaceExecutionPort,
        runner: ManagedProcessRunner | None = None,
    ) -> None:
        self.settings = settings
        self.jobs = jobs
        self._workspace = workspace
        self._runner = runner or ManagedProcessRunner()
        self._executables: dict[Interpreter, str] = {}
        if settings.enabled:
            for adapter in settings.interpreters:
                if adapter.enabled:
                    executable = shutil.which(adapter.executable)
                    if executable is None:
                        raise ConfigError(
                            "Enabled execution interpreter is unavailable",
                            key=f"execution.interpreters.{adapter.name}.executable",
                        )
                    self._executables[adapter.name] = executable

    @property
    def script_available(self) -> bool:
        return bool(self._executables)

    @property
    def shell_available(self) -> bool:
        return bool(set(self._executables) - {Interpreter.PYTHON})

    async def start(
        self,
        *,
        turn_id: str,
        interpreter: str,
        command: str | None,
        source_link: str | None,
        args: tuple[str, ...],
        cwd_link: str,
        interactive: bool,
        home: HomeService,
        operations: JoinedOperations,
    ) -> ProcessJobBackend:
        try:
            selected = Interpreter(interpreter)
        except ValueError as exc:
            raise ExecutionRequestError("Unknown interpreter") from exc
        executable = self._executables.get(selected)
        if executable is None:
            raise ExecutionRequestError("Interpreter is disabled")
        if (command is None) == (source_link is None):
            raise ExecutionRequestError("Provide exactly one command or script Link")
        if len(args) > self.settings.max_args or any(
            len(arg) > self.settings.max_arg_chars or "\x00" in arg for arg in args
        ):
            raise ExecutionRequestError("Script arguments exceed execution limits")
        source: str | None = None
        if source_link is not None:
            if source_link.startswith("workspace:"):
                read = await operations.run(
                    lambda: self._workspace.read_text(
                        source_link, max_chars=self.settings.max_source_chars
                    )
                )
            elif source_link.startswith("home:"):
                read = await home.using(operations).read_resource(
                    source_link, max_chars=self.settings.max_source_chars
                )
            else:
                raise ExecutionRequestError(
                    "Script source must be a Home or Workspace Link"
                )
            if read.truncated:
                raise ExecutionRequestError(
                    "Script source exceeds the configured limit"
                )
            source = read.text
        elif command is not None:
            if (
                selected is Interpreter.PYTHON
                or not command.strip()
                or len(command) > self.settings.max_command_chars
                or "\x00" in command
                or args
            ):
                raise ExecutionRequestError("Shell command is invalid")
        operations.check_cancelled()

        def factory(job_id: str) -> ProcessJobBackend:
            suffix = {
                Interpreter.PYTHON: ".py",
                Interpreter.BASH: ".sh",
                Interpreter.POWERSHELL: ".ps1",
                Interpreter.CMD: ".cmd",
            }[selected]
            location = self._workspace.prepare_execution(
                job_id, cwd_link=cwd_link, source_text=source, source_suffix=suffix
            )
            argv = self._argv(selected, executable, command, location.script_path, args)
            try:
                process = self._runner.start(
                    ManagedProcessRequest(
                        argv=argv,
                        cwd=str(location.cwd),
                        interactive=interactive,
                        env={"PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"},
                    ),
                    capture_root=location.capture_root,
                )
            except ManagedProcessStartError as exc:
                raise ExecutionStartError("Requested process could not start") from exc
            return ProcessJobBackend(
                job_id, process, settings=self.settings, workspace_links=location.links
            )

        async def launch(job_id: str) -> ProcessJobBackend:
            # The Registry records the returned resource before cancellation.
            return await JoinedOperations().run(lambda: factory(job_id))

        return await self.jobs.start(turn_id, ProcessJobBackend.kind, launch)

    @staticmethod
    def _argv(
        interpreter: Interpreter,
        executable: str,
        command: str | None,
        source: Path | None,
        args: tuple[str, ...],
    ) -> tuple[str, ...]:
        if source is not None:
            if interpreter is Interpreter.POWERSHELL:
                return (
                    executable,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-File",
                    str(source),
                    *args,
                )
            if interpreter is Interpreter.CMD:
                return executable, "/D", "/S", "/C", str(source), *args
            return executable, str(source), *args
        assert command is not None
        if interpreter is Interpreter.POWERSHELL:
            encoded = b64encode(command.encode("utf-16-le")).decode("ascii")
            return (
                executable,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-EncodedCommand",
                encoded,
            )
        if interpreter is Interpreter.CMD:
            return executable, "/D", "/Q", "/S", "/C", command
        return executable, "--noprofile", "--norc", "-c", command

    async def wait(self, turn_id: str, job_id: str) -> None:
        """Cancellation joins the owned process before the Action can unwind."""
        try:
            while not self.jobs.snapshot(turn_id, job_id).state.terminal:
                await asyncio.sleep(0.05)
        except BaseException:
            joined = JoinedOperations()
            await joined.finish(
                lambda: self.jobs.stop(turn_id, job_id, operations=JoinedOperations())
            )
            raise
