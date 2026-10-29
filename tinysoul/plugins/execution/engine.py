"""Execution assembly facade: resolve requests and register real process backends."""

from __future__ import annotations

import asyncio
import os
import shutil

from tinysoul.infra.concurrency import JoinedOperations
from tinysoul.infra.config import ConfigError
from tinysoul.infra.network import ResolvedNetwork
from tinysoul.infra.process import (
    ManagedProcessRequest,
    ManagedProcessRunner,
    ManagedProcessStartError,
    text_encoding,
)
from tinysoul.kernel.jobs import JobRegistry
from tinysoul.plugins.home.services import HomeService
from tinysoul.plugins.workspace.services import WorkspaceExecutionPort
from tinysoul.prompts.plugins import execution as prompt_text

from .backend import ProcessJobBackend
from .config import ExecutionSettings, Interpreter
from .failures import ExecutionRequestError, ExecutionStartError
from .interpreters import InterpreterAdapter


class ExecutionEngine:
    """No task store: all accepted executions belong to the injected JobRegistry."""

    def __init__(
        self,
        *,
        settings: ExecutionSettings,
        jobs: JobRegistry,
        workspace: WorkspaceExecutionPort,
        runner: ManagedProcessRunner | None = None,
        network: ResolvedNetwork = ResolvedNetwork(),
    ) -> None:
        self.settings = settings
        self.jobs = jobs
        self._workspace = workspace
        self._runner = runner or ManagedProcessRunner()
        self._adapters: dict[Interpreter, InterpreterAdapter] = {}
        if settings.enabled:
            for adapter in settings.interpreters:
                if adapter.enabled:
                    executable = shutil.which(adapter.executable)
                    if executable is None:
                        raise ConfigError(
                            "Enabled execution interpreter is unavailable",
                            key=f"execution.interpreters.{adapter.name}.executable",
                        )
                    assert adapter.output_encoding is not None
                    self._adapters[adapter.name] = InterpreterAdapter(
                        adapter.name, executable,
                        adapter.network.resolve(settings.network.resolve(network)),
                        text_encoding(adapter.output_encoding),
                    )

    @property
    def available_interpreters(self) -> tuple[Interpreter, ...]:
        return tuple(self._adapters)

    @property
    def script_available(self) -> bool:
        return bool(self._adapters)

    @property
    def shell_available(self) -> bool:
        return bool(set(self._adapters) - {Interpreter.PYTHON})

    async def start(
        self,
        *,
        turn_id: str,
        interpreter: str,
        command: str | None,
        source_ref: str | None,
        args: tuple[str, ...],
        cwd_ref: str,
        interactive: bool,
        home: HomeService,
        operations: JoinedOperations,
        output_encoding: str | None = None,
    ) -> ProcessJobBackend:
        try:
            selected = Interpreter(interpreter)
        except ValueError as exc:
            raise ExecutionRequestError(
                "Use one of the declared interpreter names: python, bash, powershell, or cmd."
            ) from exc
        adapter = self._adapters.get(selected)
        if adapter is None:
            raise ExecutionRequestError(
                prompt_text.interpreter_unavailable(
                    interpreter=selected.value,
                    available=tuple(item.value for item in self.available_interpreters),
                )
            )
        if (command is None) == (source_ref is None):
            raise ExecutionRequestError("Provide exactly one of command or source_ref.")
        if len(args) > self.settings.max_args or any(
            len(arg) > self.settings.max_arg_chars or "\x00" in arg for arg in args
        ):
            raise ExecutionRequestError(
                "Reduce the script arguments to the configured count and length limits."
            )
        source: str | None = None
        if source_ref is not None:
            if source_ref.startswith("workspace:"):
                read = await operations.run(
                    lambda: self._workspace.read_text(
                        source_ref, max_chars=self.settings.max_source_chars
                    )
                )
            elif source_ref.startswith("home:"):
                read = await home.using(operations).read_resource(
                    source_ref, max_chars=self.settings.max_source_chars
                )
            else:
                raise ExecutionRequestError(
                    "Use a Home or Workspace ref for script source."
                )
            if read.truncated:
                raise ExecutionRequestError(
                    "The script source exceeds the configured size limit; shorten it or split the work."
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
                raise ExecutionRequestError(
                    "For a shell command, use bash, powershell, or cmd with a non-empty command and no script args."
                )
        encoding = adapter.resolve_output_encoding(output_encoding)
        source_bytes = adapter.encode_source(source) if source is not None else None
        operations.check_cancelled()

        def factory(job_id: str) -> ProcessJobBackend:
            location = self._workspace.prepare_execution(
                job_id, cwd_ref=cwd_ref, source_bytes=source_bytes, source_suffix=adapter.suffix
            )
            launch_command = adapter.command(command, location.script_path, args)
            try:
                process = self._runner.start(
                    ManagedProcessRequest(
                        command=launch_command,
                        output_encoding=encoding,
                        cwd=str(location.cwd),
                        interactive=interactive,
                        env=adapter.network.process_environment(
                            {
                                **os.environ,
                                "PYTHONIOENCODING": "utf-8",
                                "PYTHONUNBUFFERED": "1",
                            }
                        ),
                        inherit_env=False,
                    ),
                    capture_root=location.capture_root,
                )
            except ManagedProcessStartError as exc:
                raise ExecutionStartError("Requested process could not start") from exc
            return ProcessJobBackend(
                job_id,
                process,
                settings=self.settings,
                workspace_refs=location.workspace_refs,
                result_refs=location.result_refs,
            )

        async def launch(job_id: str) -> ProcessJobBackend:
            # The Registry records the returned resource before cancellation.
            return await JoinedOperations().run(lambda: factory(job_id))

        return await self.jobs.start(turn_id, ProcessJobBackend.kind, launch)

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
