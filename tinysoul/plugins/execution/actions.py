"""Convergent execution Actions over one process-backed Job protocol."""

from enum import StrEnum

from tinysoul.infra.concurrency import JoinedOperations
from tinysoul.infra.json import JsonObject
from tinysoul.kernel.action import (
    ActionEngineBuilder,
    ActionExecution,
    ActionExecutionContext,
    ActionFailureDisposition,
    ActionLocalFailure,
    ActionResult,
    ActionResultStage,
)
from tinysoul.kernel.jobs import JobError, JobRequestError, JobState
from tinysoul.kernel.jobs.runtime_bridge import RuntimeJobsBridge
from tinysoul.plugins.home import AgentHomeContractError, AgentHomeError
from tinysoul.plugins.home.errors import AgentHomeRuntimeCopyRequired
from tinysoul.plugins.home.runtime_bridge import RuntimeAgentHomeBridge
from tinysoul.plugins.home.services import HomeService
from tinysoul.plugins.workspace import WorkspaceContractError, WorkspaceError
from tinysoul.plugins.workspace.errors import WorkspaceReconciliationError
from tinysoul.plugins.workspace.runtime_bridge import RuntimeWorkspaceBridge
from tinysoul.plugins.workspace.services import WorkspaceService

from .engine import ExecutionEngine
from .backend import ProcessJobBackend
from .failures import ExecutionRequestError, ExecutionStartError


class ExecutionOperation(StrEnum):
    RUN_SCRIPT = "run_script"
    RUN_SHELL = "run_shell"
    START = "start"
    STDIN = "stdin"
    COLLECT = "collect"


EXECUTION_ACTIONS = tuple(f"execution.{item.value}" for item in ExecutionOperation)


class ExecutionActionExecutor:
    def __init__(
        self,
        engine: ExecutionEngine,
        operation: ExecutionOperation,
        *,
        home: HomeService,
        workspace: WorkspaceService,
    ) -> None:
        self._engine, self._operation = engine, operation
        self._home, self._workspace = home, workspace

    async def execute(
        self, execution: ActionExecution, context: ActionExecutionContext
    ) -> ActionResult:
        try:
            result = await self._execute(execution, context)
        except (
            ExecutionRequestError,
            JobRequestError,
            WorkspaceContractError,
            AgentHomeContractError,
        ):
            return _failed(
                execution,
                "The execution request is unavailable or invalid.",
                "invalid_request",
            )
        except ExecutionStartError:
            return _failed(
                execution, "The requested process could not start.", "start_failed"
            )
        except JobError as exc:
            raise RuntimeJobsBridge().from_error(exc) from exc
        except AgentHomeRuntimeCopyRequired as exc:
            raise RuntimeAgentHomeBridge().runtime_copy_required(
                link=exc.link, payload=exc.to_payload()
            ) from exc
        except WorkspaceError as exc:
            raise RuntimeWorkspaceBridge().from_workspace_error(exc) from exc
        except AgentHomeError as exc:
            raise RuntimeAgentHomeBridge().from_home_error(exc) from exc
        return result

    async def _execute(
        self, execution: ActionExecution, context: ActionExecutionContext
    ) -> ActionResult:
        params = execution.call.params
        turn_id = execution.framework.turn_id
        jobs = self._engine.jobs
        operation = self._operation
        if operation in {ExecutionOperation.STDIN, ExecutionOperation.COLLECT}:
            job_id = params.get("job_id")
            if not isinstance(job_id, str) or not job_id:
                raise ExecutionRequestError("Job identity is required")
            backend = jobs.backend(turn_id, job_id, ProcessJobBackend)
            if operation is ExecutionOperation.STDIN:
                text, close = params.get("text", ""), params.get("close", False)
                if not isinstance(text, str) or not isinstance(close, bool):
                    raise ExecutionRequestError("Invalid stdin request")
                accepted = await context.owner_operations.run(
                    lambda: backend.write_stdin(text, close=close)
                )
                payload: JsonObject = {
                    "job_id": job_id,
                    "accepted_bytes": accepted,
                    "stdin_closed": close and accepted == len(text.encode("utf-8")),
                }
            else:
                stdout, stderr, limit = (
                    params.get("stdout_cursor", 0),
                    params.get("stderr_cursor", 0),
                    params.get("max_chars"),
                )
                if (
                    type(stdout) is not int
                    or type(stderr) is not int
                    or (limit is not None and type(limit) is not int)
                ):
                    raise ExecutionRequestError("Invalid collect request")
                payload = await context.owner_operations.run(
                    lambda: backend.collect(
                        stdout_cursor=stdout, stderr_cursor=stderr, max_chars=limit
                    )
                )
                payload = {**jobs.snapshot(turn_id, job_id).to_json(), **payload}
        else:
            interpreter, command, source = (
                params.get("interpreter"),
                params.get("command"),
                params.get("source_link"),
            )
            args, cwd, interactive = (
                params.get("args", []),
                params.get("cwd_link", ""),
                params.get("interactive", False),
            )
            if (
                not isinstance(interpreter, str)
                or (command is not None and not isinstance(command, str))
                or (source is not None and not isinstance(source, str))
                or not isinstance(cwd, str)
                or not isinstance(interactive, bool)
                or not isinstance(args, list)
                or any(not isinstance(item, str) for item in args)
            ):
                raise ExecutionRequestError("Invalid execution request")
            arguments = tuple(item for item in args if isinstance(item, str))
            if (
                (
                    operation is ExecutionOperation.RUN_SCRIPT
                    and (source is None or command is not None)
                )
                or (
                    operation is ExecutionOperation.RUN_SHELL
                    and (command is None or source is not None)
                )
                or (operation is not ExecutionOperation.START and interactive)
            ):
                raise ExecutionRequestError(
                    "Request does not match the execution Action"
                )
            backend = await self._engine.start(
                turn_id=turn_id,
                interpreter=interpreter,
                command=command,
                source_link=source,
                args=arguments,
                cwd_link=cwd,
                interactive=interactive,
                home=self._home,
                operations=context.owner_operations,
            )
            if operation is not ExecutionOperation.START:
                await self._engine.wait(turn_id, backend.job_id)
            payload = {
                **jobs.snapshot(turn_id, backend.job_id).to_json(),
                **await context.owner_operations.run(backend.collect),
            }

        # Files already exist in the real Workspace. Reconciliation publishes
        # metadata; cancellation never rolls those filesystem effects back.
        async def sync() -> None:
            result = await self._workspace.using(JoinedOperations()).reconcile()
            # Live Jobs may be changing the directory during discovery. The
            # owner retains its previous index; final Turn cleanup requires a
            # complete scan after all execution has stopped.
            if not result.complete and not jobs.has_unresolved(turn_id):
                raise WorkspaceReconciliationError(
                    "Execution Workspace reconciliation is incomplete"
                )

        await context.owner_operations.finish(sync)
        if (
            operation in {ExecutionOperation.RUN_SCRIPT, ExecutionOperation.RUN_SHELL}
            and payload.get("state") == JobState.FAILED.value
        ):
            return _failed(
                execution,
                "Process execution failed; existing Workspace effects remain available.",
                "process_failed",
                payload=payload,
            )
        return ActionResult.success(
            call_id=execution.call.call_id,
            invoke_id=execution.framework.invoke_id,
            batch_id=execution.framework.batch_id,
            action_name=execution.call.action_name,
            sequence=execution.call.sequence,
            domain=execution.framework.domain,
            payload=payload,
        )


def register_execution_actions(
    builder: ActionEngineBuilder,
    *,
    engine: ExecutionEngine,
    home: HomeService,
    workspace: WorkspaceService,
) -> ActionEngineBuilder:
    for operation in ExecutionOperation:
        supported = engine.script_available or engine.shell_available
        if operation is ExecutionOperation.RUN_SCRIPT:
            supported = engine.script_available
        elif operation is ExecutionOperation.RUN_SHELL:
            supported = engine.shell_available
        identity = f"execution.{operation}"
        if not supported:
            builder.mark_actions_unsupported(identity)
        else:
            builder.register_executor(
                identity,
                ExecutionActionExecutor(
                    engine, operation, home=home, workspace=workspace
                ),
            )
    return builder


def _failed(
    execution: ActionExecution,
    feedback: str,
    reason: str,
    *,
    payload: JsonObject | None = None,
) -> ActionResult:
    return ActionResult.failed(
        call_id=execution.call.call_id,
        invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id,
        action_name=execution.call.action_name,
        sequence=execution.call.sequence,
        domain=execution.framework.domain,
        stage=ActionResultStage.EXECUTE,
        failure=ActionLocalFailure(
            reason=reason,
            scope="execution.action",
            disposition=ActionFailureDisposition.CHANGE_REQUEST,
            feedback=feedback,
        ),
        payload=payload,
    )
