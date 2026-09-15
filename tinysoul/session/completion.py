"""Project typed Trace facts into immutable Session business records."""

from __future__ import annotations

from tinysoul.action.core.call import ExecutionState
from tinysoul.context import ContextTurnCompletion
from tinysoul.infra.time import BusinessDay

from .models import (
    SessionActionOutcome,
    SessionActionRecord,
    SessionInputRecord,
    SessionOutputRecord,
    SessionTurnRecord,
)


def project_turn_record(
    completion: ContextTurnCompletion,
    *,
    day: BusinessDay,
    output: SessionOutputRecord | None,
    exhausted: bool,
) -> SessionTurnRecord:
    """Preserve canonical order without inferring facts from model messages."""

    actions: list[SessionActionRecord] = []
    interrupted = {
        ExecutionState.CANCELLED: SessionActionOutcome.CANCELLED,
        ExecutionState.NOT_EXECUTED: SessionActionOutcome.NOT_EXECUTED,
        ExecutionState.UNKNOWN: SessionActionOutcome.UNKNOWN,
    }
    for fact in completion.trace.actions:
        result = fact.result
        if result is None:
            actions.append(SessionActionRecord(
                action=fact.call.action_name,
                request=fact.call.params,
                outcome=interrupted[fact.state],
            ))
            continue
        projection = result.trace_projection
        actions.append(SessionActionRecord(
            action=fact.call.action_name,
            request=fact.call.params,
            outcome=SessionActionOutcome(result.status.value),
            result=projection.canonical_payload if projection is not None else result.payload,
            failure=result.failure,
            references=projection.origin_refs if projection is not None else (),
        ))
    return SessionTurnRecord(
        ref=f"session:turn/{completion.turn_id}",
        day=str(day),
        inputs=tuple(
            SessionInputRecord(text=item.text, received_at=item.received_at)
            for item in completion.inputs
        ),
        working=completion.working,
        background_links=completion.background_links,
        output=output,
        exhausted=exhausted,
        actions=tuple(actions),
    )
