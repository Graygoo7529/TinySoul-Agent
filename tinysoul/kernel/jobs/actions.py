"""Backend-independent, convergent Job operations and wait intents."""

from math import isfinite
from enum import StrEnum
from tinysoul.infra.json import JsonObject
from tinysoul.kernel.action import ActionLocalFailure, ActionResultStage, ActionFailureDisposition

from tinysoul.kernel.action import ActionEngineBuilder, ActionExecution, ActionExecutionContext, ActionResult
from .registry import JobBackend, JobError, JobRegistry, JobState


class JobOperation(StrEnum):
    STATUS = "status"
    STOP = "stop"
    WAIT = "wait"


class JobActionExecutor[B: JobBackend]:
    def __init__(self, registry: JobRegistry[B], operation: JobOperation) -> None:
        self._registry = registry
        self._operation = operation

    async def execute(self, execution: ActionExecution, context: ActionExecutionContext) -> ActionResult:
        job_id = execution.call.params.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            return _failed(execution, "Provide an active Job identity.", reason="invalid_job")
        turn_id = execution.framework.turn_id
        try:
            snapshot = self._registry.snapshot(turn_id, job_id)
            if self._operation is JobOperation.WAIT:
                timeout = execution.call.params.get("timeout_seconds")
                if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not isfinite(timeout) or timeout <= 0):
                    return _failed(execution, "Wait timeout must be positive.", reason="invalid_wait")
                return _success(execution, {"job_id": job_id, "timeout_seconds": timeout,
                                            "ready": snapshot.state is not JobState.RUNNING})
            if self._operation is JobOperation.STOP:
                snapshot = await self._registry.stop(turn_id, job_id, operations=context.owner_operations)
                return _success(execution, snapshot.to_json())
            return _success(execution, await self._registry.describe(turn_id, job_id, operations=context.owner_operations))
        except JobError:
            return _failed(execution, "Job is not available in this Turn.", reason="unknown_job")


def register_job_actions[B: JobBackend](builder: ActionEngineBuilder, registry: JobRegistry[B]) -> None:
    for operation in JobOperation:
        builder.register_executor(f"core.job.{operation}", JobActionExecutor(registry, operation))

def _success(execution: ActionExecution, payload: JsonObject) -> ActionResult:
    return ActionResult.success(
        call_id=execution.call.call_id, invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id, action_name=execution.call.action_name,
        sequence=execution.call.sequence, domain=execution.framework.domain, payload=payload,
    )


def _failed(execution: ActionExecution, feedback: str, *, reason: str) -> ActionResult:
    return ActionResult.failed(
        call_id=execution.call.call_id, invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id, action_name=execution.call.action_name,
        sequence=execution.call.sequence, domain=execution.framework.domain,
        stage=ActionResultStage.EXECUTE,
        failure=ActionLocalFailure(reason=reason, scope="jobs.action",
            disposition=ActionFailureDisposition.CHANGE_REQUEST, feedback=feedback),
    )
