"""Backend-independent, convergent Job operations and wait intents."""

from math import isfinite
from enum import StrEnum
from tinysoul.infra.json import JsonObject
from tinysoul.kernel.action import (
    ActionLocalFailure,
    ActionResultStage,
    ActionFailureDisposition,
)

from tinysoul.kernel.action import (
    ActionEngineBuilder,
    ActionExecution,
    ActionExecutionContext,
    ActionResult,
)
from tinysoul.kernel.action import HookOutcome
from .models import JobBackend, JobState
from .registry import JobRegistry
from .failures import JobError, JobRequestError
from .runtime_bridge import RuntimeJobsBridge


class JobOperation(StrEnum):
    STATUS = "status"
    STOP = "stop"
    WAIT = "wait"


class JobActionExecutor[B: JobBackend]:
    def __init__(self, registry: JobRegistry[B], operation: JobOperation) -> None:
        self._registry = registry
        self._operation = operation

    async def execute(
        self, execution: ActionExecution, context: ActionExecutionContext
    ) -> ActionResult:
        job_id = execution.call.params.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            return _failed(
                execution, "Provide an active Job identity.", reason="invalid_job"
            )
        turn_id = execution.framework.turn_id
        try:
            snapshot = self._registry.snapshot(turn_id, job_id)
            if self._operation is JobOperation.WAIT:
                timeout = execution.call.params.get("timeout_seconds")
                if timeout is not None and (
                    isinstance(timeout, bool)
                    or not isinstance(timeout, (int, float))
                    or not isfinite(timeout)
                    or timeout <= 0
                ):
                    return _failed(
                        execution,
                        "Wait timeout must be positive.",
                        reason="invalid_wait",
                    )
                return _success(
                    execution,
                    {
                        "job_id": job_id,
                        "timeout_seconds": timeout,
                        "ready": snapshot.state.terminal,
                    },
                )
            if self._operation is JobOperation.STOP:
                snapshot = await self._registry.stop(
                    turn_id, job_id, operations=context.owner_operations
                )
                return _success(execution, snapshot.to_json())
            return _success(
                execution,
                await self._registry.describe(
                    turn_id, job_id, operations=context.owner_operations
                ),
            )
        except JobRequestError:
            return _failed(
                execution, "Job is not available in this Turn.", reason="unknown_job"
            )
        except JobError as exc:
            raise RuntimeJobsBridge().from_error(exc) from exc


def register_job_actions[B: JobBackend](
    builder: ActionEngineBuilder, registry: JobRegistry[B]
) -> ActionEngineBuilder:
    for operation in JobOperation:
        builder.register_executor(
            f"core.job.{operation}", JobActionExecutor(registry, operation)
        )
    builder.register_execution_hook("jobs.answer_guard", JobAnswerGuard(registry))
    builder.use_action_execution_hooks("core.answer", "jobs.answer_guard")
    return builder


class JobAnswerGuard[B: JobBackend]:
    def __init__(self, registry: JobRegistry[B]) -> None:
        self._registry = registry

    def check(
        self, execution: ActionExecution, context: ActionExecutionContext
    ) -> HookOutcome:
        if self._registry.has_unresolved(execution.framework.turn_id):
            return HookOutcome.reject(
                ActionLocalFailure(
                    reason="live_job",
                    scope="jobs.answer_guard",
                    disposition=ActionFailureDisposition.CHANGE_REQUEST,
                    feedback="Wait for or stop the active Job before answering.",
                )
            )
        return HookOutcome.success()


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


def _failed(execution: ActionExecution, feedback: str, *, reason: str) -> ActionResult:
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
            scope="jobs.action",
            disposition=ActionFailureDisposition.CHANGE_REQUEST,
            feedback=feedback,
        ),
    )
