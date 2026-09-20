"""Project typed Trace facts into immutable Session business records."""

from __future__ import annotations

from tinysoul.kernel.action.call import ExecutionState
from tinysoul.kernel.context import ContextTurnCompletion
from tinysoul.kernel.context.builtin.trace import TraceKind
from tinysoul.infra.json import JsonObject
from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.loop.outcomes import TurnFailure, TurnOutcomeStatus

from .records.models import (
    SessionActionOutcome,
    SessionActionRecord,
    SessionInputRecord,
    SessionOutputRecord,
    SessionTurnRecord,
    SessionFact,
)


def project_turn_record(
    completion: ContextTurnCompletion,
    *,
    day: CalendarDay,
    output: SessionOutputRecord | None,
    exhausted: bool,
    status: TurnOutcomeStatus,
    failure: TurnFailure | None = None,
    finish_failures: tuple[TurnFailure, ...] = (),
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
            actions.append(
                SessionActionRecord(
                    action=fact.call.action_name,
                    request=fact.call.params,
                    outcome=interrupted[fact.state],
                )
            )
            continue
        projection = result.trace_projection
        actions.append(
            SessionActionRecord(
                action=fact.call.action_name,
                result_id=result.result_id,
                request=fact.call.params,
                outcome=SessionActionOutcome(result.status.value),
                result=(
                    projection.canonical_payload
                    if projection is not None
                    else result.payload
                ),
                failure=result.failure,
                references=projection.origin_refs if projection is not None else (),
            )
        )
    turn_ref = f"session:turn/{completion.turn_id}"
    trace_root = f"turn:trace@{completion.turn_id}"
    refs = {
        f"{trace_root}#input/{item.input_id}": f"{turn_ref}#input/{index}"
        for index, item in enumerate(completion.inputs)
    }
    refs.update({
        f"{trace_root}#action/{index}": f"{turn_ref}#action/{index}"
        for index in range(len(actions))
    })
    notes: list[JsonObject] = []
    for entry in completion.trace.entries:
        if entry.kind is TraceKind.ACTION_RESULT:
            continue  # Action canonical results already have their own records.
        value = entry.to_semantic()
        value.pop("actions", None)  # Requests belong to typed Action records.
        if value == {"kind": "decision"}:
            continue
        refs[f"{trace_root}#entry/{entry.entry_id}"] = f"{turn_ref}#note/{len(notes)}"
        notes.append(value)
    timeline = tuple(
        SessionFact(item.kind, refs[item.ref], item.admission_sequence)
        for item in completion.trace.timeline
        if item.ref in refs
    )
    return SessionTurnRecord(
        ref=f"session:turn/{completion.turn_id}",
        day=str(day),
        inputs=tuple(
            SessionInputRecord(
                text=item.text,
                received_at=item.received_at,
                input_id=item.input_id,
                reply_to=item.reply_to,
            )
            for item in completion.inputs
        ),
        working=completion.working,
        segments=completion.segments,
        background_links=completion.background_links,
        output=output,
        exhausted=exhausted,
        status=status,
        failure=failure,
        finish_failures=finish_failures,
        actions=tuple(actions),
        timeline=timeline,
        notes=tuple(notes),
    )
