"""Core Turn segments: identity, accepted inputs, execution trace and plan."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from tinysoul.infra.continuation import (
    ContinuationError,
    ContinuationFailureReason,
    OpaqueContinuationCodec,
    continue_json_sequence,
)
from tinysoul.infra.json import JsonObject, JsonValue, dumps_json, to_json_object
from tinysoul.llm.protocol.messages import (
    AssistantMessage,
    JsonPart,
    Message,
    SystemMessage,
    TextPart,
    ToolResultMessage,
    UserMessage,
)
from tinysoul.llm.protocol.tools import ToolKind
from tinysoul.runtime import Signal

from ..errors import (
    ContextInvariantError,
    ContextInspectFailureReason,
    ContextInspectRequestError,
)
from ..segments import (
    ContextSegment,
    ReadOnlySegmentRegistration,
    RegisteredSegment,
    SegmentCapability,
    SegmentDescriptor,
    SegmentRegistration,
    SegmentReclaim,
    SegmentShape,
    SegmentSlot,
    TurnInfo,
)
from ..signals import (
    SIGNAL_INPUT_APPEND,
    SIGNAL_TRACE_APPEND,
    SIGNAL_WORKING_PATCH,
    InputAppend,
    TraceAppend,
    parse_input_append_signal,
    parse_trace_append_signal,
    parse_working_patch_signal,
)
from .trace import PendingInputs, TraceEntry, TurnTraceHeap
from .working import WorkingContext, WorkingPatch

IDENTITY = SegmentDescriptor("identity", "context", SegmentSlot.BACKGROUND, 10)
INPUTS = SegmentDescriptor("inputs", "context", SegmentSlot.BACKGROUND, 30)
TRACE = SegmentDescriptor(
    "trace",
    "context",
    SegmentSlot.TRACE,
    10,
    ref_prefixes=("turn:trace",),
    shape=SegmentShape.STACK,
    capabilities=frozenset({SegmentCapability.INSPECT, SegmentCapability.RECLAIM}),
)
PLAN = SegmentDescriptor("plan", "context", SegmentSlot.WORKING, 10)
JOURNAL = SegmentDescriptor("journal", "context", SegmentSlot.BACKGROUND, 39)
CORE_DESCRIPTORS = (IDENTITY, INPUTS, TRACE, PLAN, JOURNAL)
CORE_SEGMENT_IDS = frozenset(item.id for item in CORE_DESCRIPTORS)


@dataclass(frozen=True)
class CoreSegmentProvider[S: ContextSegment]:
    """Bind a newly created core view to its single Turn's registry."""

    segment: S

    async def open(self, info: TurnInfo) -> S:
        return self.segment


@dataclass(frozen=True)
class FixedTextSegment:
    text: str
    identity: bool = False

    def render(self) -> tuple[Message, ...]:
        if not self.text:
            return ()
        if self.identity:
            return (SystemMessage.from_text(self.text, label="identity"),)
        return (UserMessage.from_text(self.text, label="background:journal"),)

    def seal(self) -> JsonObject:
        return {"text": self.text}

    async def close(self) -> None:
        pass


class InputsSegment:
    def __init__(self, initial: str | None = None) -> None:
        self.state = PendingInputs()
        if initial is not None:
            self.state.add(initial, merged=True)

    async def prepare(self, updates: tuple[InputAppend, ...]) -> PendingInputs:
        candidate = deepcopy(self.state)
        for update in updates:
            candidate.add(
                update.text, input_id=update.input_id, reply_to=update.reply_to
            )
        return candidate

    def install(self, prepared: PendingInputs) -> None:
        self.state = prepared

    def render(self) -> tuple[Message, ...]:
        return self.state.render_messages()

    def seal(self) -> JsonObject:
        # Typed completion owns input bodies; the segment snapshot only names
        # those same facts, as Session does for its prior-Turn view.
        return {"input_ids": [item.input_id for item in self.state.all()]}

    async def close(self) -> None:
        pass


class PlanSegment:
    def __init__(self) -> None:
        self.state = WorkingContext()

    async def prepare(self, updates: tuple[WorkingPatch, ...]) -> WorkingContext:
        candidate = deepcopy(self.state)
        for patch in updates:
            candidate.apply_patch(patch)
        return candidate

    def install(self, prepared: WorkingContext) -> None:
        self.state = prepared

    def render(self) -> tuple[Message, ...]:
        return self.state.render_messages()

    def seal(self) -> JsonObject:
        return self.state.to_json()

    async def close(self) -> None:
        pass


class TraceSegment:
    def __init__(self, trace: TurnTraceHeap, *, inspect_max_chars: int) -> None:
        self.state = trace
        self._trace_inspect_max_chars = inspect_max_chars
        self._trace_continuations = OpaqueContinuationCodec(
            owner="context", operation="inspect"
        )

    async def prepare(self, updates: tuple[TraceAppend, ...]) -> TurnTraceHeap:
        candidate = deepcopy(self.state)
        for update in updates:
            if update.decision is not None:
                candidate.append_decision(
                    update.decision, cycle_id=update.cycle_id, phase=update.phase
                )
            elif update.action_result is not None:
                candidate.append_action_result(
                    update.action_result,
                    cycle_id=update.cycle_id,
                    canonical_message=update.canonical_action_result,
                    origin_refs=update.origin_refs,
                )
            elif update.note is not None:
                candidate.append_phase_note(
                    update.note, cycle_id=update.cycle_id, phase=update.phase
                )
        return candidate

    def install(self, prepared: TurnTraceHeap) -> None:
        self.state = prepared

    def render(self) -> tuple[Message, ...]:
        return self.state.render_messages()

    def seal(self) -> JsonObject:
        # Canonical execution facts travel through typed ContextTurnCompletion.
        # The serializable view only identifies the current inspection root.
        return {"ref": self.state.head_ref()}

    def reclaim(self, required_chars: int) -> SegmentReclaim:
        return SegmentReclaim(
            self.state.compact(required_chars=required_chars).reclaimed_chars
        )

    async def inspect(self, ref: str, *, continuation: str | None = None) -> JsonObject:
        return self.inspect_view(ref, continuation=continuation)

    def inspect_view(self, ref: str, *, continuation: str | None = None) -> JsonObject:
        structure = self.state.inspect(ref)
        if structure.get("kind") != "context_trace_leaf":
            if continuation is not None:
                raise ContextInspectRequestError(
                    ContextInspectFailureReason.INVALID_CONTINUATION,
                    "This Context node has no continuation; inspect its child ref",
                    constraint={"ref": ref},
                )
            if len(dumps_json(structure)) > self._trace_inspect_max_chars:
                raise ContextInspectRequestError(
                    ContextInspectFailureReason.PAGE_BUDGET_TOO_SMALL,
                    "Context heap header exceeds the inspect character limit",
                    constraint={"ref": ref},
                )
            return structure
        interactions = tuple(
            _semantic_trace_entry(entry) for entry in self.state.leaf_entries(ref)
        )
        try:
            return continue_json_sequence(
                interactions,
                base={"kind": "context_trace_leaf", "ref": ref},
                item_field="interactions",
                continuation=continuation,
                codec=self._trace_continuations,
                ref=ref,
                max_chars=self._trace_inspect_max_chars,
            )
        except ContinuationError as exc:
            raise _context_continuation_error(exc, ref=ref) from exc

    async def close(self) -> None:
        pass


def _working_update(signal: Signal) -> WorkingPatch:
    return parse_working_patch_signal(signal)[1]


def core_registrations(
    *,
    identity: str,
    journal: str,
    inputs: InputsSegment,
    plan: PlanSegment,
    trace: TraceSegment,
) -> tuple[RegisteredSegment, ...]:
    return (
        ReadOnlySegmentRegistration(
            IDENTITY, CoreSegmentProvider(FixedTextSegment(identity, True))
        ),
        ReadOnlySegmentRegistration(
            JOURNAL, CoreSegmentProvider(FixedTextSegment(journal))
        ),
        SegmentRegistration(
            INPUTS,
            CoreSegmentProvider(inputs),
            SIGNAL_INPUT_APPEND,
            InputAppend,
            parse_input_append_signal,
        ),
        SegmentRegistration(
            PLAN,
            CoreSegmentProvider(plan),
            SIGNAL_WORKING_PATCH,
            WorkingPatch,
            _working_update,
        ),
        SegmentRegistration(
            TRACE,
            CoreSegmentProvider(trace),
            SIGNAL_TRACE_APPEND,
            TraceAppend,
            parse_trace_append_signal,
        ),
    )


def _context_continuation_error(
    error: ContinuationError,
    *,
    ref: str,
) -> ContextInspectRequestError:
    reason_map = {
        ContinuationFailureReason.INVALID: (
            ContextInspectFailureReason.INVALID_CONTINUATION
        ),
        ContinuationFailureReason.MISMATCH: (
            ContextInspectFailureReason.INVALID_CONTINUATION
        ),
        ContinuationFailureReason.OUT_OF_RANGE: (
            ContextInspectFailureReason.INVALID_CONTINUATION
        ),
        ContinuationFailureReason.CONTENT_CHANGED: (
            ContextInspectFailureReason.INVALID_CONTINUATION
        ),
        ContinuationFailureReason.BUDGET_TOO_SMALL: (
            ContextInspectFailureReason.PAGE_BUDGET_TOO_SMALL
        ),
    }
    reason = reason_map.get(error.reason)
    if reason is None:
        raise ContextInvariantError(
            "Unexpected Context continuation failure"
        ) from error
    return ContextInspectRequestError(
        reason,
        str(error),
        constraint={"ref": ref},
    )


def _semantic_trace_entry(entry: TraceEntry) -> JsonObject:
    message = entry.message
    content = _semantic_parts(message)
    if isinstance(message, AssistantMessage):
        value: JsonObject = {"kind": "decision"}
        if content:
            value["content"] = content[0] if len(content) == 1 else content
        actions: list[JsonValue] = [
            to_json_object({"action": call.name, "request": call.arguments})
            for call in message.tool_calls
            if call.kind is ToolKind.ACTION
        ]
        controls: list[JsonValue] = [
            to_json_object({"control": call.name, "request": call.arguments})
            for call in message.tool_calls
            if call.kind is ToolKind.CONTROL
        ]
        if actions:
            value["actions"] = actions
        if controls:
            value["controls"] = controls
        return to_json_object(value)
    if isinstance(message, ToolResultMessage):
        value = {
            "kind": "action_result",
            "action": message.tool_name,
            "outcome": message.status.value,
        }
        envelope = (
            content[0] if len(content) == 1 and isinstance(content[0], dict) else None
        )
        if envelope is not None:
            status = envelope.get("status")
            if isinstance(status, str) and status:
                value["outcome"] = status
            payload = envelope.get("payload")
            if isinstance(payload, dict) and payload:
                value["result"] = payload
            failure = envelope.get("failure")
            if isinstance(failure, dict) and failure:
                value["failure"] = {
                    key: failure[key]
                    for key in ("reason", "disposition", "feedback", "constraint")
                    if key in failure
                }
        elif content:
            value["result"] = content[0] if len(content) == 1 else content
        if entry.origin_refs:
            value["references"] = list(entry.origin_refs)
        return to_json_object(value)
    value = {"kind": "phase_note"}
    if content:
        value["content"] = content[0] if len(content) == 1 else content
    return to_json_object(value)


def _semantic_parts(message: Message) -> list[JsonValue]:
    values: list[JsonValue] = []
    for part in message.parts:
        if isinstance(part, TextPart):
            values.append(part.text)
        elif isinstance(part, JsonPart):
            values.append(part.value)
    return values
