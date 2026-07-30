"""ActionEngine integration for immediate Shell execution."""

from __future__ import annotations

from hashlib import sha256
from typing import Protocol

from tinysoul.action import (
    ActionEngineBuilder,
    ActionExecution,
    ActionExecutionContext,
    ActionExecutor,
    ActionFailureDisposition,
    ActionLocalFailure,
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
)

from .config import ShellAdapterSettings, ShellSettings
from .dependencies import require_shell_dependencies
from .errors import ShellError
from .models import ShellInterpreter
from .policy import ShellPolicy
from .process import ShellProcessPreparer


SHELL_ACTIONS = (
    "execution.run_powershell",
    "execution.run_cmd",
    "execution.run_bash_command",
)


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
                reason="invalid_run",
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
                reason="workspace_mirror_changed",
            )
        except (ShellError, SupervisedProcessError, WorkspaceContractError) as exc:
            return _failed(
                execution,
                "Shell execution could not start.",
                reason="shell_start_failed",
                disposition=ActionFailureDisposition.STOP,
                frame_data={"error_type": type(exc).__name__},
            )
        except WorkspaceError as exc:
            _raise_workspace_error(exc, self._workspace_bridge)
        return _observation_result(execution, observation)


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
            "execution.run_powershell",
            "shell.run_powershell",
            settings.powershell,
        ),
        (
            ShellInterpreter.CMD,
            "execution.run_cmd",
            "shell.run_cmd",
            settings.cmd,
        ),
        (
            ShellInterpreter.BASH,
            "execution.run_bash_command",
            "shell.run_bash",
            settings.bash,
        ),
    )
    policy = ShellPolicy(max_command_chars=settings.max_command_chars)
    for interpreter, action_name, handler, adapter in adapters:
        if not adapter.enabled:
            builder.disable_actions(action_name)
            continue
        builder.register_executor(
            handler,
            ShellRunExecutor(
                interpreter=interpreter,
                adapter=adapter,
                policy=policy,
                jobs=jobs,
                bus=bus,
                workspace_bridge=workspace_bridge,
            ),
        )
    return builder


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
            failure=ActionLocalFailure(
                reason="shell_job_timeout",
                scope="shell.execution",
                disposition=ActionFailureDisposition.CHANGE_REQUEST,
                feedback=(
                    "Shell job reached its configured timeout and must be discarded."
                ),
            ),
            payload=observation.payload,
            frame_data={"executor_leaked": False},
        )
    if observation.failed:
        return _failed(
            execution,
            "Shell process failed. Logs and candidates remain inspectable but cannot be applied.",
            reason="shell_process_failed",
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
    *,
    reason: str,
    disposition: ActionFailureDisposition = ActionFailureDisposition.CHANGE_REQUEST,
    frame_data: JsonObject | None = None,
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
        failure=ActionLocalFailure(
            reason=reason,
            scope="shell.action",
            disposition=disposition,
            feedback=feedback,
        ),
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
