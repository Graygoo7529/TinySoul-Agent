"""The Agent's single write entry for source-backed Session explanations."""

from collections.abc import Callable

from tinysoul.kernel.action import (
    ActionEngineBuilder,
    ActionExecution,
    ActionExecutionContext,
    ActionExecutor,
    ActionResult,
    ActionResultStage,
    ActionLocalFailure,
    ActionFailureDisposition,
)
from tinysoul.kernel.context import ContextTurnFacts
from tinysoul.runtime import Signal
from .annotations.models import (
    OrganizeChange,
    OrganizeRequestError,
    OrganizeFailureReason,
)
from .errors import SessionError
from .services import SessionOrganizeService
from .projection import SESSION_CONTEXT_UPDATE
from .runtime_bridge import RuntimeSessionBridge


def register_session_actions(
    builder: ActionEngineBuilder,
    *,
    service: SessionOrganizeService,
    facts: Callable[[], ContextTurnFacts],
) -> ActionEngineBuilder:
    builder.register_executor(
        "core.session.organize", SessionOrganizeExecutor(service, facts)
    )
    return builder


class SessionOrganizeExecutor(ActionExecutor):
    def __init__(
        self, service: SessionOrganizeService, facts: Callable[[], ContextTurnFacts]
    ) -> None:
        self._service, self._facts = service, facts

    async def execute(
        self, execution: ActionExecution, context: ActionExecutionContext
    ) -> ActionResult:
        bus = context.require_signal_bus()
        try:
            change = OrganizeChange.parse(execution.call.params)
        except OrganizeRequestError as exc:
            return _failed(execution, exc.reason, str(exc))
        facts = self._facts()
        try:
            result = await self._service.using(context.owner_operations).organize(
                change, facts
            )
        except SessionError as exc:
            raise RuntimeSessionBridge().from_session_error(exc) from exc
        if result.failure is not None:
            return _failed(execution, result.failure, result.feedback)
        bus.emit(
            Signal(
                name=SESSION_CONTEXT_UPDATE,
                source="core.session.organize",
                scope=execution.framework.scope,
                payload={"refresh": True},
            )
        )
        return ActionResult.success(
            call_id=execution.call.call_id,
            invoke_id=execution.framework.invoke_id,
            batch_id=execution.framework.batch_id,
            action_name=execution.call.action_name,
            sequence=execution.call.sequence,
            domain=execution.framework.domain,
            payload={
                "changed_refs": list(result.changed_refs),
                "created_refs": dict(result.created),
            },
        )


def _failed(
    execution: ActionExecution, reason: OrganizeFailureReason, feedback: str
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
            reason=reason.value,
            scope="session.organize",
            disposition=ActionFailureDisposition.CHANGE_REQUEST,
            feedback=feedback,
        ),
    )
