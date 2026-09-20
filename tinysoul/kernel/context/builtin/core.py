"""Core Turn segments: identity, accepted inputs, execution trace and plan."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from tinysoul.infra.continuation import (
    ContinuationError,
    ContinuationFailureReason,
    OpaqueContinuationCodec,
)
from tinysoul.infra.json import JsonObject, dumps_json
from tinysoul.llm.protocol.messages import (
    AssistantMessage,
    Message,
    SystemMessage,
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
from ..disclosure import DisclosureHint, DisclosurePage, query_hint
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
    capabilities=frozenset({SegmentCapability.INSPECT, SegmentCapability.QUERY, SegmentCapability.RECLAIM}),
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
                update.text, input_id=update.input_id, reply_to=update.reply_to,
                received_at=update.received_at,
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
                    update.note, cycle_id=update.cycle_id, phase=update.phase,
                    admission_sequence=update.admission_sequence,
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

    async def inspect(
        self,
        ref: str,
        *,
        query: str | None = None,
        continuation: str | None = None,
    ) -> JsonObject:
        entries = self.state.entries_for_ref(ref)
        if query is not None:
            matches = []
            for entry in entries:
                if _inspect_interaction(entry):
                    continue
                hint = query_hint(
                    self.state.entry_ref(entry.entry_id),
                    entry.kind.value,
                    entry.to_semantic(),
                    query,
                )
                if hint is not None:
                    matches.append(hint)
            page = DisclosurePage(ref, "context_query", children=tuple(matches))
        elif "#entry/" in ref:
            page = DisclosurePage(
                ref,
                "context_trace_entry",
                content=tuple(item.to_semantic() for item in entries),
                sources=tuple(dict.fromkeys(
                    source for item in entries for source in item.origin_refs
                )),
            )
        else:
            children = []
            structure = self.state.inspect(ref)
            nodes = structure.get("nodes", [])
            assert isinstance(nodes, list)
            for node in nodes:
                assert isinstance(node, dict)
                children.append(DisclosureHint(
                    str(node["ref"]), str(node["kind"]), dumps_json(node)
                ))
            if ref == self.state.head_ref():
                entries = self.state.hot_entries()
            elif structure.get("kind") == "context_trace_branch":
                entries = ()
            children.extend(
                DisclosureHint(
                    self.state.entry_ref(item.entry_id), item.kind.value,
                    dumps_json(item.to_semantic())[:240],
                )
                for item in entries
            )
            page = DisclosurePage(ref, "context_trace", children=tuple(children))
        try:
            return page.render(
                codec=self._trace_continuations,
                max_chars=self._trace_inspect_max_chars,
                continuation=continuation,
                binding={"query": query},
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


def _inspect_interaction(entry: TraceEntry) -> bool:
    message = entry.message
    if isinstance(message, ToolResultMessage):
        return message.tool_name == "core.context.inspect"
    return isinstance(message, AssistantMessage) and bool(message.tool_calls) and all(
        call.name == "core.context.inspect" for call in message.tool_calls
    )
