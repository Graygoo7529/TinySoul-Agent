"""Action hooks owned by the shared supervised process lifecycle."""

from tinysoul.action import ActionExecution, ActionExecutionContext
from tinysoul.action.core.hooks import HookOutcome

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
            return HookOutcome.failed(
                "Resolve the active process job before answering.",
                frame_data={"reason": "unresolved_supervised_process_job"},
            )
        return HookOutcome.success()
