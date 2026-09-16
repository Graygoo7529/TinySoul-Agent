"""Small synthetic Turn builders independent of persisted runtime examples."""

from __future__ import annotations

from dataclasses import dataclass, field

from tinysoul.kernel.action import (
    ActionCall,
    ActionFailureDisposition,
    ActionLocalFailure,
    ActionResultEnvelope,
    ActionResult,
    ActionTraceProjection,
    ActionResultStage,
    ActionResultStatus,
)
from tinysoul.kernel.context import (
    ContextTurnCompletion,
    ContextTurnInput,
)
from tinysoul.kernel.action.core.call import ExecutionState
from tinysoul.kernel.context.trace import SealedTurnTrace, TraceAction, TraceEntry, TraceKind
from tinysoul.infra.json import JsonObject
from tinysoul.llm import AssistantMessage, ToolResultMessage
from tinysoul.llm.tools import ToolCallRecord, ToolKind, ToolResultStatus
from tinysoul.runtime import CyclePhase


@dataclass(frozen=True)
class SyntheticAction:
    name: str
    request: JsonObject = field(default_factory=dict)
    result: JsonObject = field(default_factory=dict)
    status: ActionResultStatus = ActionResultStatus.SUCCESS
    failure_reason: str = "action_failed"
    references: tuple[str, ...] = ()


def completion(
    turn_id: str,
    *,
    ask: str = "question",
    received_at: float = 1.0,
    working: JsonObject | None = None,
    background_links: tuple[str, ...] = (),
    actions: tuple[SyntheticAction, ...] = (),
) -> ContextTurnCompletion:
    entries: list[TraceEntry] = []
    facts: list[TraceAction] = []
    if actions:
        calls = tuple(
            ToolCallRecord(
                id=f"call_{index}",
                name=action.name,
                arguments=action.request,
                kind=ToolKind.ACTION,
            )
            for index, action in enumerate(actions)
        )
        entries.append(
            TraceEntry(
                entry_id="decision_actions",
                kind=TraceKind.DECISION,
                message=AssistantMessage.from_tool_calls(*calls),
                cycle_id="cycle_1",
                phase=CyclePhase.PHASE2,
            )
        )
        for index, action in enumerate(actions):
            failure = None
            tool_status = ToolResultStatus.OK
            if action.status is not ActionResultStatus.SUCCESS:
                failure = ActionLocalFailure(
                    reason=action.failure_reason,
                    scope=action.name,
                    disposition=ActionFailureDisposition.CHANGE_REQUEST,
                    feedback="The action did not complete.",
                )
                tool_status = ToolResultStatus.ERROR
            envelope = ActionResultEnvelope(
                action_name=action.name,
                status=action.status,
                stage=(
                    ActionResultStage.TIMEOUT
                    if action.status is ActionResultStatus.TIMEOUT
                    else ActionResultStage.EXECUTE
                ),
                payload=action.result,
                failure=failure,
            )
            facts.append(TraceAction(
                cycle_id="cycle_1",
                call=ActionCall(call_id=f"call_{index}", action_name=action.name,
                                params=action.request, sequence=index + 1),
                state=ExecutionState.SETTLED,
                result=ActionResult(
                    result_id=f"result_{index}",
                    call_id=f"call_{index}", action_name=action.name,
                    sequence=index + 1, status=action.status,
                    stage=envelope.stage, payload=action.result, failure=failure,
                    trace_projection=ActionTraceProjection(
                        origin_refs=action.references, canonical_payload=action.result,
                    ) if action.references else None,
                ),
            ))
            entries.append(
                TraceEntry(
                    entry_id=f"result_{index}",
                    kind=TraceKind.ACTION_RESULT,
                    message=ToolResultMessage.from_json(
                        call_id=f"call_{index}",
                        tool_name=action.name,
                        value=envelope.to_json(),
                        status=tool_status,
                    ),
                    cycle_id="cycle_1",
                    phase=CyclePhase.PHASE3,
                    origin_refs=action.references,
                )
            )
    return ContextTurnCompletion(
        turn_id=turn_id,
        inputs=(ContextTurnInput(text=ask, received_at=received_at),),
        working=working or {},
        background_links=background_links,
        trace=SealedTurnTrace(turn_id=turn_id, entries=tuple(entries), actions=tuple(facts)),
    )
