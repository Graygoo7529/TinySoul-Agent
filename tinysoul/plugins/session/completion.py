"""Project typed Trace facts into immutable Session business records."""

from __future__ import annotations

from tinysoul.kernel.action.call import ExecutionState
from tinysoul.kernel.context import (
    ContextTurnCompletion,
    ContextTurnInput,
)
from tinysoul.kernel.context.builtin.trace import TraceKind, TraceAction
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


def project_action_record(fact: TraceAction) -> SessionActionRecord:
    result = fact.result
    if result is None:
        interrupted = {
            ExecutionState.CANCELLED: SessionActionOutcome.CANCELLED,
            ExecutionState.NOT_EXECUTED: SessionActionOutcome.NOT_EXECUTED,
            ExecutionState.UNKNOWN: SessionActionOutcome.UNKNOWN,
        }
        return SessionActionRecord(
            action=fact.call.action_name,
            request=fact.call.params,
            outcome=interrupted[fact.state],
        )
    projection = result.trace_projection
    return SessionActionRecord(
        action=fact.call.action_name,
        result_id=result.result_id,
        request=fact.call.params,
        outcome=SessionActionOutcome(result.status.value),
        result=projection.canonical_payload
        if projection is not None
        else result.payload,
        failure=result.failure,
        references=projection.origin_refs if projection else (),
    )


def project_fact_refs(
    turn_id: str,
    inputs: tuple[ContextTurnInput, ...],
    action_count: int,
) -> dict[str, str]:
    root, target = f"turn:trace@{turn_id}", f"session:turn/{turn_id}"
    return {
        **{
            f"{root}#input/{item.input_id}": f"{target}#input/{index}"
            for index, item in enumerate(inputs)
        },
        **{
            f"{root}#action/{index}": f"{target}#action/{index}"
            for index in range(action_count)
        },
    }


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

    actions = tuple(project_action_record(fact) for fact in completion.trace.actions)
    turn_ref = f"session:turn/{completion.turn_id}"
    trace_root = f"turn:trace@{completion.turn_id}"
    refs = project_fact_refs(completion.turn_id, completion.inputs, len(actions))
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
