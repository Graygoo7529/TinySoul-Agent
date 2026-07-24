"""Action hooks owned by the shared supervised process lifecycle."""

from tinysoul.action import (
    ActionExecution,
    ActionExecutionContext,
    ActionFailureDisposition,
    ActionLocalFailure,
    HookOutcome,
)

from .manager import SupervisedProcessManager


class SupervisedProcessAnswerGuard:
    """Prevent a final answer while a Turn owns an unresolved process job."""

    def __init__(self, jobs: SupervisedProcessManager) -> None:
        self._jobs = jobs

    def check(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> HookOutcome:
        del context
        if self._jobs.has_unresolved(execution.framework.turn_id):
            return HookOutcome.reject(
                ActionLocalFailure(
                    reason="unresolved_supervised_process_job",
                    scope="supervised_process.answer_guard",
                    disposition=ActionFailureDisposition.CHANGE_REQUEST,
                    feedback="Resolve the active process job before answering.",
                )
            )
        return HookOutcome.success()
