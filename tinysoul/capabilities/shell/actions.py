"""ActionEngine integration for immediate Shell execution."""

from __future__ import annotations

from hashlib import sha256
from typing import Protocol

from tinysoul.action import (
    ActionEngineBuilder,
    ActionExecution,
    ActionExecutionContext,
    ActionExecutor,
    ActionResult,
    ActionResultStage,
)
from tinysoul.capabilities.supervised_process import (
    SupervisedProcessManager,
    SupervisedProcessObservation,
    SupervisedProcessOwner,
)
from tinysoul.capabilities.supervised_process.errors import SupervisedProcessError
from tinysoul.infra import JsonObject
from tinysoul.runtime import RuntimeException, SignalBus
from tinysoul.workspace import (
    WorkspaceContractError,
    WorkspaceError,
    WorkspaceMirrorConflict,
    workspace_snapshot_signal,
)

from .config import ShellAdapterSettings, ShellSettings
from .dependencies import require_shell_dependencies
from .errors import ShellError
from .models import ShellInterpreter
from .policy import ShellPolicy
from .process import ShellProcessPreparer


SHELL_ACTIONS = (
    "shell.run_powershell",
    "shell.run_cmd",
    "shell.run_bash",
    "shell.wait",
    "shell.stop",
    "shell.read_candidate",
    "shell.apply",
    "shell.discard",
)

_LIFECYCLE_ACTIONS = SHELL_ACTIONS[3:]


class ShellWorkspaceRuntimeBridge(Protocol):
    def from_workspace_error(
        self,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException: ...


class ShellRunExecutor(ActionExecutor):
    def __init__(
        self,
        *,
        interpreter: ShellInterpreter,
        adapter: ShellAdapterSettings,
        policy: ShellPolicy,
        jobs: SupervisedProcessManager,
        bus: SignalBus,
        workspace_bridge: ShellWorkspaceRuntimeBridge | None,
    ) -> None:
        self._interpreter = interpreter
        self._adapter = adapter
        self._policy = policy
        self._jobs = jobs
        self._bus = bus
        self._workspace_bridge = workspace_bridge

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        command = execution.call.params.get("command")
        working_directory = execution.call.params.get("working_directory", ".")
        if not isinstance(command, str) or not isinstance(working_directory, str):
            return _failed(
                execution,
                "Shell run parameters are invalid.",
                {"reason": "invalid_run"},
            )
        try:
            self._policy.validate(command)
            observation = self._jobs.start(
                turn_id=execution.framework.turn_id,
                owner=SupervisedProcessOwner.SHELL,
                identity={
                    "command_digest": sha256(command.encode("utf-8")).hexdigest(),
                    "interpreter": self._interpreter.value,
                    "working_directory": working_directory,
                },
                prepare=ShellProcessPreparer(
                    interpreter=self._interpreter,
                    adapter=self._adapter,
                    command=command,
                    working_directory=working_directory,
                ),
                control=context.control,
                bus=context.signal_bus or self._bus,
                auto_complete_without_changes=True,
            )
        except WorkspaceMirrorConflict:
            return _failed(
                execution,
                "Workspace changed while the Shell execution mirror was prepared.",
                {"reason": "workspace_mirror_changed"},
            )
        except (ShellError, SupervisedProcessError, WorkspaceContractError) as exc:
            return _failed(
                execution,
                "Shell execution could not start.",
                {"reason": "shell_start_failed", "error_type": type(exc).__name__},
            )
        except WorkspaceError as exc:
            _raise_workspace_error(exc, self._workspace_bridge)
        return _observation_result(execution, observation)


class ShellJobExecutor(ActionExecutor):
    def __init__(
        self,
        *,
        operation: str,
        jobs: SupervisedProcessManager,
        bus: SignalBus,
        workspace_bridge: ShellWorkspaceRuntimeBridge | None,
    ) -> None:
        self._operation = operation
        self._jobs = jobs
        self._bus = bus
        self._workspace_bridge = workspace_bridge

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        execution_id = _required_text(execution, "execution_id")
        if execution_id is None:
            return _failed(
                execution,
                "Shell job action requires execution_id.",
                {"reason": "missing_execution_id"},
            )
        try:
            if self._operation == "wait":
                wait = execution.call.params.get(
                    "wait_seconds",
                    self._jobs.settings.default_wait_seconds,
                )
                if isinstance(wait, bool) or not isinstance(wait, int):
                    return _failed(
                        execution,
                        "Shell wait_seconds must be an integer.",
                        {"reason": "invalid_wait"},
                    )
                return _observation_result(
                    execution,
                    self._jobs.wait(
                        turn_id=execution.framework.turn_id,
                        owner=SupervisedProcessOwner.SHELL,
                        execution_id=execution_id,
                        wait_seconds=wait,
                        control=context.control,
                        bus=context.signal_bus or self._bus,
                    ),
                )
            if self._operation == "stop":
                return _observation_result(
                    execution,
                    self._jobs.stop(
                        turn_id=execution.framework.turn_id,
                        owner=SupervisedProcessOwner.SHELL,
                        execution_id=execution_id,
                    ),
                )
            if self._operation == "read_candidate":
                path = _required_text(execution, "path")
                cursor = execution.call.params.get("cursor", 0)
                max_chars = execution.call.params.get(
                    "max_chars",
                    self._jobs.settings.max_candidate_read_chars,
                )
                if (
                    path is None
                    or isinstance(cursor, bool)
                    or not isinstance(cursor, int)
                    or isinstance(max_chars, bool)
                    or not isinstance(max_chars, int)
                ):
                    return _failed(
                        execution,
                        "Shell candidate read parameters are invalid.",
                        {"reason": "invalid_candidate_read"},
                    )
                return _success(
                    execution,
                    self._jobs.read_candidate(
                        turn_id=execution.framework.turn_id,
                        owner=SupervisedProcessOwner.SHELL,
                        execution_id=execution_id,
                        path=path,
                        cursor=cursor,
                        max_chars=max_chars,
                    ),
                )
            if self._operation == "apply":
                applied = self._jobs.apply(
                    turn_id=execution.framework.turn_id,
                    owner=SupervisedProcessOwner.SHELL,
                    execution_id=execution_id,
                )
                (context.signal_bus or self._bus).emit(
                    workspace_snapshot_signal(
                        applied.manifest,
                        call_id=execution.call.call_id,
                        scope=execution.framework.scope,
                        source="shell.apply",
                    )
                )
                return _success(execution, applied.payload)
            if self._operation == "discard":
                return _success(
                    execution,
                    self._jobs.discard(
                        turn_id=execution.framework.turn_id,
                        owner=SupervisedProcessOwner.SHELL,
                        execution_id=execution_id,
                    ),
                )
        except WorkspaceMirrorConflict:
            return _failed(
                execution,
                "Shell apply conflicts with a concurrently changed Workspace path. "
                "The job remains available for review or discard.",
                {"reason": "workspace_apply_conflict"},
            )
        except (ShellError, SupervisedProcessError, WorkspaceContractError) as exc:
            return _failed(
                execution,
                "Shell job operation failed.",
                {"reason": "shell_job_failed", "error_type": type(exc).__name__},
            )
        except WorkspaceError as exc:
            _raise_workspace_error(exc, self._workspace_bridge)
        return _failed(
            execution,
            "Shell job operation is unavailable.",
            {"reason": "unknown_job_operation"},
        )


def register_shell_actions(
    builder: ActionEngineBuilder,
    *,
    settings: ShellSettings,
    jobs: SupervisedProcessManager,
    bus: SignalBus,
    workspace_bridge: ShellWorkspaceRuntimeBridge | None = None,
) -> ActionEngineBuilder:
    require_shell_dependencies(settings)
    if not settings.enabled:
        builder.disable_actions(*SHELL_ACTIONS)
        return builder
    adapters = (
        (
            ShellInterpreter.POWERSHELL,
            "shell.run_powershell",
            settings.powershell,
        ),
        (ShellInterpreter.CMD, "shell.run_cmd", settings.cmd),
        (ShellInterpreter.BASH, "shell.run_bash", settings.bash),
    )
    enabled_count = 0
    policy = ShellPolicy(max_command_chars=settings.max_command_chars)
    for interpreter, action_name, adapter in adapters:
        if not adapter.enabled:
            builder.disable_actions(action_name)
            continue
        enabled_count += 1
        builder.register_executor(
            action_name,
            ShellRunExecutor(
                interpreter=interpreter,
                adapter=adapter,
                policy=policy,
                jobs=jobs,
                bus=bus,
                workspace_bridge=workspace_bridge,
            ),
        )
    if enabled_count == 0:
        builder.disable_actions(*_LIFECYCLE_ACTIONS)
        return builder
    for operation in ("wait", "stop", "read_candidate", "apply", "discard"):
        builder.register_executor(
            f"shell.{operation}",
            ShellJobExecutor(
                operation=operation,
                jobs=jobs,
                bus=bus,
                workspace_bridge=workspace_bridge,
            ),
        )
    return builder


def _required_text(execution: ActionExecution, name: str) -> str | None:
    value = execution.call.params.get(name)
    return value if isinstance(value, str) and value else None


def _observation_result(
    execution: ActionExecution,
    observation: SupervisedProcessObservation,
) -> ActionResult:
    if observation.timed_out:
        return ActionResult.timeout(
            call_id=execution.call.call_id,
            invoke_id=execution.framework.invoke_id,
            batch_id=execution.framework.batch_id,
            action_name=execution.call.action_name,
            sequence=execution.call.sequence,
            domain=execution.framework.domain,
            model_feedback=(
                "Shell job reached its configured timeout and must be discarded."
            ),
            payload=observation.payload,
            frame_data={"reason": "shell_job_timeout", "executor_leaked": False},
        )
    if observation.failed:
        return _failed(
            execution,
            "Shell process failed. Logs and candidates remain inspectable but cannot be applied.",
            {"reason": "shell_process_failed"},
            payload=observation.payload,
        )
    return _success(execution, observation.payload)


def _success(execution: ActionExecution, payload: JsonObject) -> ActionResult:
    return ActionResult.success(
        call_id=execution.call.call_id,
        invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id,
        action_name=execution.call.action_name,
        sequence=execution.call.sequence,
        domain=execution.framework.domain,
        payload=payload,
    )


def _failed(
    execution: ActionExecution,
    feedback: str,
    frame_data: JsonObject,
    *,
    payload: JsonObject | None = None,
) -> ActionResult:
    return ActionResult.failed(
        call_id=execution.call.call_id,
        invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id,
        action_name=execution.call.action_name,
        stage=ActionResultStage.EXECUTE,
        sequence=execution.call.sequence,
        domain=execution.framework.domain,
        model_feedback=feedback,
        frame_data=frame_data,
        payload=payload,
    )


def _raise_workspace_error(
    exc: WorkspaceError,
    bridge: ShellWorkspaceRuntimeBridge | None,
) -> None:
    if bridge is None:
        raise exc
    raise bridge.from_workspace_error(
        exc,
        payload={"capability": "shell"},
    ) from exc
