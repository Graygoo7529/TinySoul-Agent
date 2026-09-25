"""Context module assembly facade."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from uuid import uuid4
from tinysoul.kernel.action.call import ActionCall, ExecutionFact, ExecutionState
from tinysoul.kernel.action.result import ActionResult

from tinysoul.infra.concurrency import CleanupDiagnostic
from tinysoul.infra.continuation import MIN_CONTINUATION_PAGE_CHARS
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.llm.protocol.messages import MessageStack, ToolResultMessage
from tinysoul.infra.references import ReferenceResolver
from tinysoul.infra.continuation import OpaqueContinuationCodec
from tinysoul.kernel.retrieval.contracts import SearchRequest, SeedRefinement
from tinysoul.kernel.retrieval.operations import SearchCorpus
from .disclosure import DisclosureSearchEntry, DisclosureReference, DisclosurePage
from .search import disclosure_corpus
from tinysoul.llm.protocol.tools import ToolCallRecord, ToolScope
from tinysoul.runtime import (
    NullObservationEmitter,
    ObservationEmitter,
    ObservationEvent,
    ObservationLevel,
    RunLevel,
    RunScope,
    Signal,
    SignalBus,
    emit_observation,
    observation_enabled,
)

from .background import (
    BackgroundPatch,
    check_background_patches,
)
from .projection.composer import ContextBudget, MessageStackComposer
from .compress import ContextCompressor, ContextPressureReport
from .config import ContextSettings
from .control.tools import (
    ContextControlScopeBuilder,
    ControlCallNormalizer,
    ControlNormalization,
    ControlResult,
    ControlResultStage,
)
from .errors import (
    ContextContractError,
    ContextInvariantError,
    ContextInspectFailureReason,
    ContextInspectRequestError,
)
from .prompts import TaskPrompt
from .providers import SegmentSelectionView
from .signals import (
    SIGNAL_BACKGROUND_PATCH,
    SIGNAL_INPUT_APPEND,
    SIGNAL_NAMESPACE,
    SIGNAL_TRACE_APPEND,
    SIGNAL_WORKING_PATCH,
    parse_background_patch_signal,
    parse_working_patch_signal,
    parse_input_append_signal,
    build_trace_phase_note_signal,
)
from .builtin.trace import (
    PendingInputs,
    SealedTurnTrace,
    TraceCompactionReport,
    TraceKind,
    TraceFactKind,
    TraceAction,
    TurnTraceHeap,
)
from .builtin.working import WorkingContext, WorkingPatch
from .segments import RegisteredSegment, SegmentRegistry, TurnInfo, TurnSegments
from .builtin.core import (
    CORE_DESCRIPTORS,
    CORE_SEGMENT_IDS,
    InputsSegment,
    PlanSegment,
    TraceSegment,
    core_registrations,
)


@dataclass(frozen=True)
class ContextTurnInput:
    """One immutable user input transferred at Turn completion."""

    text: str
    received_at: float
    input_id: str = field(default_factory=lambda: f"input_{uuid4().hex}")
    reply_to: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text:
            raise ContextContractError("ContextTurnInput.text must be non-empty")
        if (
            isinstance(self.received_at, bool)
            or not isinstance(self.received_at, (int, float))
            or self.received_at < 0
        ):
            raise ContextContractError(
                "ContextTurnInput.received_at must be non-negative"
            )


@dataclass(frozen=True)
class ContextTurnFacts:
    """Read-only input/Action facts while a Turn is still executing."""

    turn_id: str
    inputs: tuple[ContextTurnInput, ...]
    actions: tuple[TraceAction, ...]

    def __post_init__(self) -> None:
        if not self.turn_id or not self.inputs:
            raise ContextContractError("Current facts require a Turn and its input")
        if any(not isinstance(item, ContextTurnInput) for item in self.inputs):
            raise ContextContractError("Current facts require typed inputs")
        if any(not isinstance(item, TraceAction) for item in self.actions):
            raise ContextContractError("Current facts require typed Actions")


@dataclass(frozen=True)
class ContextTurnCompletion:
    """Typed current-Turn facts transferred once through the completion pipeline."""

    turn_id: str
    inputs: tuple[ContextTurnInput, ...]
    working: JsonObject
    background_links: tuple[str, ...]
    trace: SealedTurnTrace
    segments: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.turn_id:
            raise ContextContractError(
                "ContextTurnCompletion.turn_id must be non-empty"
            )
        inputs = tuple(self.inputs)
        if not inputs or any(not isinstance(item, ContextTurnInput) for item in inputs):
            raise ContextContractError(
                "ContextTurnCompletion.inputs must contain typed inputs"
            )
        object.__setattr__(self, "inputs", inputs)
        object.__setattr__(self, "working", to_json_object(self.working))
        object.__setattr__(self, "segments", to_json_object(self.segments))
        links = tuple(self.background_links)
        if any(not isinstance(link, str) or not link for link in links):
            raise ContextContractError(
                "ContextTurnCompletion.background_links must contain non-empty strings"
            )
        if len(set(links)) != len(links):
            raise ContextContractError(
                "ContextTurnCompletion.background_links must be unique"
            )
        object.__setattr__(self, "background_links", links)
        if not isinstance(self.trace, SealedTurnTrace):
            raise ContextContractError(
                "ContextTurnCompletion.trace must be a SealedTurnTrace"
            )
        if self.trace.turn_id != self.turn_id:
            raise ContextContractError(
                "ContextTurnCompletion trace must belong to the same Turn"
            )
        root = f"turn:trace@{self.turn_id}"
        refs = {
            *(f"{root}#input/{item.input_id}" for item in inputs),
            *(f"{root}#entry/{item.entry_id}" for item in self.trace.entries),
            *(f"{root}#action/{index}" for index in range(len(self.trace.actions))),
        }
        if any(item.ref not in refs for item in self.trace.timeline):
            raise ContextInvariantError("Turn timeline references an unknown fact")


@dataclass(frozen=True)
class ContextSignalBatch:
    """A replayable group of context signals owned by one active Turn."""

    turn_id: str
    signals: tuple[Signal, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.turn_id:
            raise ContextContractError("ContextSignalBatch.turn_id must be non-empty")
        signals = tuple(self.signals)
        if any(not isinstance(signal, Signal) for signal in signals):
            raise ContextContractError(
                "ContextSignalBatch.signals must contain Signal values"
            )
        object.__setattr__(self, "signals", signals)


class ContextEngine:
    """Assembled context module entry point for loop integration."""

    def __init__(
        self,
        *,
        composer: MessageStackComposer,
        system_text: str,
        compressor: ContextCompressor,
        journal: str,
        registrations: tuple[RegisteredSegment, ...],
        trace_inspect_max_chars: int,
        compression_trigger_ratio: float,
        compression_target_ratio: float,
        observations: ObservationEmitter | None = None,
    ) -> None:
        self._composer = composer
        self._system_text = system_text
        self._segment_registry = SegmentRegistry()
        self._turn_registry = SegmentRegistry()
        self._segments: TurnSegments | None = None
        self._compressor = compressor
        self._journal = journal
        self._trace_inspect_max_chars = trace_inspect_max_chars
        self._compression_trigger_ratio = compression_trigger_ratio
        self._compression_target_ratio = compression_target_ratio
        self._observations = observations or NullObservationEmitter()
        self._scope_builder = ContextControlScopeBuilder()
        self._normalizer = ControlCallNormalizer()
        self._plan_segment = PlanSegment()
        self._trace_segment = TraceSegment(
            compressor.new_trace("detached"), inspect_max_chars=trace_inspect_max_chars
        )
        self._inputs_segment = InputsSegment()
        self._turn_id = ""
        for registration in registrations:
            self.register_segment(registration)

    @property
    def _trace(self) -> TurnTraceHeap:
        return self._trace_segment.state

    @property
    def _inputs(self) -> PendingInputs:
        return self._inputs_segment.state

    @property
    def _working(self) -> WorkingContext:
        return self._plan_segment.state

    @property
    def turn_active(self) -> bool:
        return bool(self._turn_id)

    @property
    def compression_trigger_ratio(self) -> float:
        return self._compression_trigger_ratio

    @property
    def compression_target_ratio(self) -> float:
        return self._compression_target_ratio

    def background_links(self) -> tuple[str, ...]:
        """Return currently loaded background links without exposing mutable state."""

        return self._selection_view().loaded

    def working_snapshot(self) -> JsonObject:
        """Return a JSON-safe copy of the working context."""

        self._require_turn()
        return to_json_object(self._working.to_json())

    def register_segment(self, registration: RegisteredSegment) -> None:
        self.register_segments((registration,))

    def register_segments(self, registrations: tuple[RegisteredSegment, ...]) -> None:
        """Validate a complete contribution batch before changing the registry."""
        self._segment_registry = self._candidate_segments(registrations)

    def validate_segments(self, registrations: tuple[RegisteredSegment, ...]) -> None:
        """Check contribution routes without installing providers or opening a Turn."""
        self._candidate_segments(registrations)

    def _candidate_segments(
        self, registrations: tuple[RegisteredSegment, ...]
    ) -> SegmentRegistry:
        if self._turn_id or self._segments is not None:
            raise ContextContractError(
                "Segments must be registered before Turn execution"
            )
        candidate = self._segment_registry
        for registration in registrations:
            if registration.descriptor.id in CORE_SEGMENT_IDS | {"task_prompt"}:
                raise ContextContractError(
                    "Segment id conflicts with a core projection"
                )
            for prefix in registration.descriptor.ref_prefixes:
                if any(
                    prefix.startswith(reserved) or reserved.startswith(prefix)
                    for descriptor in CORE_DESCRIPTORS
                    for reserved in descriptor.ref_prefixes
                ):
                    raise ContextContractError(
                        "Segment reference route conflicts with a core segment"
                    )
            if registration.signal_name in {
                SIGNAL_WORKING_PATCH,
                SIGNAL_BACKGROUND_PATCH,
                SIGNAL_TRACE_APPEND,
                SIGNAL_INPUT_APPEND,
            }:
                raise ContextContractError(
                    "Segment update route conflicts with a core update"
                )
            candidate = candidate.register(registration)
        return candidate

    def segment_snapshot(self, segment_id: str) -> JsonObject:
        self._require_turn()
        value = (
            self._segments.seal().get(segment_id)
            if self._segments is not None
            else None
        )
        if not isinstance(value, dict):
            raise ContextContractError("No active segment has this identity")
        return to_json_object(value)

    async def close_segments(self) -> tuple[CleanupDiagnostic, ...]:
        segments = self._segments
        if segments is None:
            return ()
        try:
            return await segments.close()
        finally:
            self._segments = None

    def trace_kinds(self) -> tuple[TraceKind, ...]:
        """Return trace entry kinds for observation and tests."""

        self._require_turn()
        return tuple(entry.kind for entry in self._trace.entries())

    def begin_turn(self, user_input: str, *, turn_id: str = "") -> str:
        if self._turn_id or self._segments is not None:
            raise ContextContractError(
                "Previous Turn must be ended and its segments closed"
            )
        if not user_input:
            raise ContextContractError("begin_turn requires non-empty user input")
        if not isinstance(turn_id, str) or (turn_id and not turn_id.strip()):
            raise ContextContractError(
                "Turn identity must be non-empty text when supplied"
            )
        self._turn_id = turn_id or f"turn_{uuid4().hex[:8]}"
        self._plan_segment = PlanSegment()
        self._trace_segment = TraceSegment(
            self._compressor.new_trace(self._turn_id),
            inspect_max_chars=self._trace_inspect_max_chars,
        )
        self._inputs_segment = InputsSegment(user_input)
        initial = self._inputs.all()[0]
        self._trace.record_fact(
            TraceFactKind.INPUT_INSTALLED, self._trace.input_ref(initial.input_id)
        )
        self._trace.record_fact(
            TraceFactKind.INPUT_VISIBLE, self._trace.input_ref(initial.input_id)
        )
        self._turn_registry = SegmentRegistry(
            (
                *core_registrations(
                    identity=self._system_text,
                    journal=self._journal,
                    inputs=self._inputs_segment,
                    plan=self._plan_segment,
                    trace=self._trace_segment,
                ),
                *self._segment_registry.registrations,
            )
        )
        return self._turn_id

    async def open_segments(self, active_day: date) -> None:
        """Open every owner view before the first model task."""
        self._require_turn()
        if not isinstance(active_day, date):
            raise ContextContractError("Segment preparation requires a date")
        if self._segments is not None:
            return
        self._search_day = active_day
        views = self._turn_registry.for_turn(TurnInfo(self._turn_id, active_day))
        await views.open()
        try:
            views.selection_view()  # Reject overlapping dynamic catalogs before publishing views.
        except Exception:
            await views.close()
            raise
        self._segments = views
        self._emit_background_observation(
            name="context.background.snapshot",
            message="Turn background views opened.",
        )

    def _selection_view(self) -> SegmentSelectionView:
        return (
            self._segments.selection_view()
            if self._segments is not None
            else SegmentSelectionView()
        )

    def compose(self, task_prompt: TaskPrompt) -> MessageStack:
        self._require_turn()
        if self._segments is None:
            raise ContextContractError(
                "Context segments must be opened before composition"
            )
        return self._composer.compose(
            segments=self._segments.render(), task_prompt=task_prompt
        )

    def control_scope(self) -> ToolScope:
        self._require_turn()
        view = self._selection_view()
        return self._scope_builder.build(
            loadable_links=tuple(
                ref for ref in view.available if ref not in view.loaded
            ),
            loaded_links=tuple(ref for ref in view.loaded if ref not in view.protected),
        )

    def mark_model_consumed(self, messages: MessageStack) -> None:
        self._require_turn()
        self._trace.mark_consumed(messages.messages)

    def normalize_controls(
        self,
        tool_calls: tuple[ToolCallRecord, ...],
        *,
        scope: RunScope,
    ) -> ControlNormalization:
        self._require_turn()
        return self._normalizer.normalize(tool_calls, scope=scope)

    def take_signal_batch(self, bus: SignalBus) -> ContextSignalBatch:
        """Remove the current context namespace from the bus as a replayable batch."""

        self._require_turn()
        return ContextSignalBatch(
            turn_id=self._turn_id,
            signals=bus.consume_namespace(SIGNAL_NAMESPACE),
        )

    async def consume_signals(self, bus: SignalBus) -> tuple[ControlResult, ...]:
        """Capture one batch, await its reads, then install its prepared state."""

        return await self.consume_signal_batch(self.take_signal_batch(bus))

    async def consume_signal_batch(
        self,
        batch: ContextSignalBatch,
    ) -> tuple[ControlResult, ...]:
        """Prepare and atomically commit a replayable context signal batch.

        Model control failures become local results; invalid owner updates stop at
        the contract boundary. Valid working/background patches are
        checked against a projected batch state. Lazy background content is fully
        loaded before the first state mutation, so a Runtime Trap can retry this
        exact batch without observing a partial commit.
        """

        self._require_turn()
        if batch.turn_id != self._turn_id:
            raise ContextContractError(
                "Context signal batch belongs to a different active Turn"
            )
        background_before = self.background_links()
        results: list[ControlResult] = []
        working_candidates: list[tuple[int, Signal, str, WorkingPatch]] = []
        segment_signals: list[tuple[int, Signal]] = []
        background_candidates: list[tuple[int, Signal, str, BackgroundPatch]] = []

        for index, signal in enumerate(batch.signals):
            sequence = index + 1
            scope_problem = self._signal_scope_problem(signal)
            if scope_problem:
                if self._segments is not None and self._segments.accepts(signal):
                    raise ContextContractError(
                        "Registered segment update has invalid Turn scope"
                    )
                results.append(
                    _consume_failure(
                        signal,
                        _signal_call_id(signal),
                        sequence,
                        scope_problem,
                    )
                )
                continue
            try:
                if signal.name == SIGNAL_WORKING_PATCH:
                    call_id, patch = parse_working_patch_signal(signal)
                    working_candidates.append((sequence, signal, call_id, patch))
                elif self._segments is not None and self._segments.accepts(signal):
                    segment_signals.append((sequence, signal))
                elif signal.name == SIGNAL_BACKGROUND_PATCH:
                    call_id, patch = parse_background_patch_signal(signal)
                    background_candidates.append((sequence, signal, call_id, patch))
                else:
                    results.append(
                        _consume_failure(
                            signal,
                            "",
                            sequence,
                            f"Unknown context signal: {signal.name}",
                        )
                    )
            except ContextContractError as exc:
                results.append(
                    _consume_failure(
                        signal,
                        _signal_call_id(signal),
                        sequence,
                        str(exc),
                    )
                )

        problems = self._working.check_patch_sequence(
            tuple(patch for _, _, _, patch in working_candidates)
        )
        for (sequence, signal, call_id, _patch), problem in zip(
            working_candidates, problems
        ):
            if problem:
                results.append(_consume_failure(signal, call_id, sequence, problem))
            else:
                segment_signals.append((sequence, signal))
                segment_signals.append(
                    (
                        sequence,
                        build_trace_phase_note_signal(
                            {"kind": "plan_changed", "patch": signal.payload["patch"]},
                            scope=signal.scope,
                            source="context.plan",
                        ),
                    )
                )
        problems = check_background_patches(
            self._selection_view(),
            tuple(patch for _, _, _, patch in background_candidates),
        )
        for (sequence, signal, call_id, patch), problem in zip(
            background_candidates, problems
        ):
            if problem:
                results.append(_consume_failure(signal, call_id, sequence, problem))
            elif self._segments is not None:
                segment_signals.extend(
                    (sequence, update)
                    for update in self._segments.selection_signals(patch, signal)
                )

        if self._segments is not None:
            ordered = tuple(
                signal
                for _, signal in sorted(segment_signals, key=lambda item: item[0])
            )
            entry_count = len(self._trace.entries())
            prepared_segments = await self._segments.prepare(ordered)
            if self._turn_id != batch.turn_id:
                raise ContextContractError("Segment preparation outlived its Turn")
            self._segments.install(prepared_segments)
            entries = iter(self._trace.entries()[entry_count:])
            for signal in ordered:
                if signal.name == SIGNAL_INPUT_APPEND:
                    update = parse_input_append_signal(signal)
                    self._trace.record_fact(
                        TraceFactKind.INPUT_INSTALLED,
                        self._trace.input_ref(update.input_id),
                        admission_sequence=update.admission_sequence,
                    )
                elif signal.name == SIGNAL_TRACE_APPEND:
                    entry = next(entries)
                    self._trace.record_fact(
                        TraceFactKind.ENTRY,
                        self._trace.entry_ref(entry.entry_id),
                        cycle_id=entry.cycle_id,
                        admission_sequence=entry.admission_sequence,
                    )

        background_after = self.background_links()
        if background_after != background_before:
            before = set(background_before)
            after = set(background_after)
            self._emit_background_observation(
                name="context.background.changed",
                message="Top-level background context changed.",
                loaded_links=tuple(
                    link for link in background_after if link not in before
                ),
                evicted_links=tuple(
                    link for link in background_before if link not in after
                ),
            )
        return tuple(sorted(results, key=lambda result: result.sequence))

    def merge_pending_inputs(self) -> int:
        self._require_turn()
        unmerged = self._inputs.unmerged()
        self._inputs.mark_merged(tuple(item.input_id for item in unmerged))
        for item in unmerged:
            self._trace.record_fact(
                TraceFactKind.INPUT_VISIBLE, self._trace.input_ref(item.input_id)
            )
        return len(unmerged)

    def compress(self, *, required_chars: int = 1) -> TraceCompactionReport:
        self._require_turn()
        return self._compressor.compress(
            self._trace,
            required_chars=required_chars,
        )

    def reclaim_pressure(self, *, required_chars: int) -> ContextPressureReport:
        self._require_turn()
        from .segments import SegmentReclaim

        background_report = (
            self._segments.reclaim(required_chars)
            if self._segments is not None
            else SegmentReclaim()
        )
        report = ContextPressureReport(
            changed=bool(background_report.reclaimed_chars),
            reclaimed_chars=(background_report.reclaimed_chars),
            evicted_background_links=background_report.evicted_refs,
        )
        if background_report.evicted_refs:
            self._emit_background_observation(
                name="context.background.changed",
                message="Top-level background context evicted for budget.",
                evicted_links=background_report.evicted_refs,
            )
        return report

    def _emit_background_observation(
        self,
        *,
        name: str,
        message: str,
        loaded_links: tuple[str, ...] = (),
        evicted_links: tuple[str, ...] = (),
    ) -> None:
        if not observation_enabled(self._observations, ObservationLevel.VERBOSE):
            return
        emit_observation(
            self._observations,
            ObservationEvent(
                name=name,
                level=ObservationLevel.VERBOSE,
                source="context.engine",
                scope=RunScope().push(RunLevel.TURN, self._turn_id),
                message=message,
                payload={
                    "turn_id": self._turn_id,
                    "links": list(self.background_links()),
                    "loaded_links": list(loaded_links),
                    "evicted_links": list(evicted_links),
                },
            ),
        )

    async def inspect(
        self,
        ref: str,
        *,
        query: str | None = None,
        continuation: str | None = None,
    ) -> JsonObject:
        self._require_turn()
        if self._segments is None:
            raise ContextContractError(
                "Context segments must be opened before inspection"
            )
        if query is not None and (not isinstance(query, str) or not query.strip()):
            raise ContextInspectRequestError(
                ContextInspectFailureReason.INVALID_QUERY,
                "Query must be non-empty text",
            )
        fact = next(
            (item for item in self._current_search_facts() if item.ref == ref), None
        )
        if fact is not None:
            return DisclosurePage(ref, "context_fact", content=(fact.content,)).render(
                codec=OpaqueContinuationCodec(
                    owner="context", operation="inspect_fact"
                ),
                max_chars=self._trace_inspect_max_chars,
                continuation=continuation,
            )
        return await self._segments.inspect(ref, query=query, continuation=continuation)

    async def search_corpus(
        self, request: SearchRequest, *, references: ReferenceResolver
    ) -> SearchCorpus:
        self._require_turn()
        if self._segments is None:
            raise ContextContractError("Context segments must be opened before search")
        seeds = request.seed_refs if isinstance(request, SeedRefinement) else ()
        current = (
            self._current_search_facts()
            if request.options.scope in {"all", "trace"}
            else ()
        )
        current_ids = {item.ref for item in current}
        remaining_seeds = tuple(ref for ref in seeds if ref not in current_ids)
        entries = (
            await self._segments.search_entries(request.options.scope, remaining_seeds)
            if not seeds or remaining_seeds
            else ()
        )
        selected = tuple(
            item
            for item in current
            if not seeds or item.ref in seeds or self._trace.head_ref() in seeds
        )
        return disclosure_corpus((*entries, *selected), request, references)

    def _current_search_facts(self) -> tuple[DisclosureSearchEntry, ...]:
        # This is a pure current-fact read. It never seals, settles or renumbers
        # actions, including requested actions preceding a terminal subset.
        result = []
        day = self._search_day
        for item in self._inputs.all():
            ref = self._trace.input_ref(item.input_id)
            result.append(
                DisclosureSearchEntry(
                    ref,
                    "User input",
                    {"kind": "input", "text": item.text, "reply_to": item.reply_to},
                    "trace",
                    day=day,
                )
            )
        for action in self._trace.actions():
            if action.state in {ExecutionState.REQUESTED, ExecutionState.STARTED}:
                continue
            ref = self._trace.action_ref(action.cycle_id, action.call.sequence)
            content: JsonObject = {
                "kind": "action_fact",
                "action": action.call.action_name,
                "state": action.state.value,
                "request": action.call.params,
            }
            refs = ()
            if action.result is not None:
                content["result"] = action.result.envelope().to_json()
                if action.result.trace_projection:
                    refs = tuple(
                        DisclosureReference(target, source_day=day)
                        for target in action.result.trace_projection.origin_refs
                    )
            result.append(
                DisclosureSearchEntry(
                    ref,
                    action.call.action_name,
                    content,
                    "trace",
                    references=refs,
                    day=day,
                )
            )
        return tuple(result)

    def record_execution(self, fact: ExecutionFact) -> None:
        self._require_turn()
        self._trace.record_execution(fact)

    def register_action_calls(
        self, calls: tuple[ActionCall, ...], *, cycle_id: str
    ) -> None:
        self._require_turn()
        self._trace.register_action_calls(calls, cycle_id=cycle_id)

    def record_action_result(self, result: ActionResult, *, cycle_id: str) -> None:
        self._require_turn()
        self._trace.record_action_result(result, cycle_id=cycle_id)

    def seal_trace(self) -> SealedTurnTrace:
        self._require_turn()
        return self._trace.seal()

    def current_facts(self) -> ContextTurnFacts:
        """Capture on the event loop; owners may then read this value off-loop."""
        self._require_turn()
        return ContextTurnFacts(
            self._turn_id,
            tuple(
                ContextTurnInput(
                    text=item.text,
                    received_at=item.received_at,
                    input_id=item.input_id,
                    reply_to=item.reply_to,
                )
                for item in self._inputs.all()
            ),
            self._trace.actions(),
        )

    def end_turn(self) -> ContextTurnCompletion:
        self._require_turn()
        completion = ContextTurnCompletion(
            turn_id=self._turn_id,
            inputs=tuple(
                ContextTurnInput(
                    text=item.text,
                    received_at=item.received_at,
                    input_id=item.input_id,
                    reply_to=item.reply_to,
                )
                for item in self._inputs.all()
            ),
            working=self._working.to_json(),
            background_links=self.background_links(),
            trace=self._trace.seal(),
            segments={
                key: value
                for key, value in (
                    self._segments.seal() if self._segments is not None else {}
                ).items()
                if key not in CORE_SEGMENT_IDS
            },
        )
        self._turn_id = ""
        self._preparing_turn = False
        return completion

    def abort_turn(self) -> None:
        """Discard the active turn state when summary finalization cannot complete."""

        if not self._turn_id:
            return
        self._turn_id = ""

        self._preparing_turn = False

    def _require_turn(self) -> None:
        if not self._turn_id:
            raise ContextContractError("No active turn")

    def _signal_scope_problem(self, signal: Signal) -> str:
        turn = signal.scope.nearest(RunLevel.TURN)
        if turn is None:
            return "Context signal has no Turn scope"
        if turn.name != self._turn_id:
            return (
                "Context signal belongs to another Turn: "
                f"expected {self._turn_id}, received {turn.name}"
            )
        return ""


def _consume_failure(
    signal: Signal,
    call_id: str,
    sequence: int,
    model_feedback: str,
) -> ControlResult:
    return ControlResult.failed(
        call_id=call_id or f"signal_{sequence}",
        tool_name=signal.name,
        stage=ControlResultStage.CONSUME,
        sequence=sequence,
        model_feedback=model_feedback,
        frame_data={"signal": signal.name, "source": signal.source},
    )


class ContextEngineBuilder:
    """Assemble a ContextEngine from configuration."""

    @classmethod
    def from_settings(cls, settings: ContextSettings) -> "ContextEngineBuilder":
        return (
            cls(system_text=settings.system_text)
            .with_journal(settings.journal)
            .with_budget_max_image_bytes(settings.budget_max_image_bytes)
            .with_trace_heap(
                chunk_max_chars=settings.trace_chunk_max_chars,
                branch_factor=settings.trace_branch_factor,
                min_hot_entries=settings.trace_min_hot_entries,
            )
            .with_trace_inspect_max_chars(settings.trace_inspect_max_chars)
            .with_compression_trigger_ratio(settings.compression_trigger_ratio)
            .with_compression_target_ratio(settings.compression_target_ratio)
        )

    def __init__(self, *, system_text: str) -> None:
        if not system_text:
            raise ContextContractError(
                "ContextEngineBuilder requires non-empty system text"
            )
        self._system_text = system_text
        self._journal = ""
        self._max_image_bytes: int | None = None
        self._trace_chunk_max_chars = 12000
        self._trace_branch_factor = 4
        self._trace_min_hot_entries = 2
        self._trace_inspect_max_chars = 8000
        self._compression_trigger_ratio = 0.80
        self._compression_target_ratio = 0.50
        self._registrations: list[RegisteredSegment] = []
        self._observations: ObservationEmitter = NullObservationEmitter()

    def with_journal(self, journal: str) -> "ContextEngineBuilder":
        self._journal = journal
        return self

    def with_observations(
        self,
        observations: ObservationEmitter,
    ) -> "ContextEngineBuilder":
        if not hasattr(observations, "enabled") or not hasattr(observations, "emit"):
            raise ContextContractError(
                "Context observations must provide enabled() and emit()"
            )
        self._observations = observations
        return self

    def with_budget_max_image_bytes(
        self,
        max_image_bytes: int | None,
    ) -> "ContextEngineBuilder":
        if max_image_bytes is not None and max_image_bytes <= 0:
            raise ContextContractError("Context image byte budget must be positive")
        self._max_image_bytes = max_image_bytes
        return self

    def with_trace_heap(
        self,
        *,
        chunk_max_chars: int,
        branch_factor: int,
        min_hot_entries: int,
    ) -> "ContextEngineBuilder":
        if chunk_max_chars <= 0:
            raise ContextContractError("Trace chunk_max_chars must be positive")
        if branch_factor < 2:
            raise ContextContractError("Trace branch_factor must be at least 2")
        if min_hot_entries < 0:
            raise ContextContractError("Trace min_hot_entries cannot be negative")
        self._trace_chunk_max_chars = chunk_max_chars
        self._trace_branch_factor = branch_factor
        self._trace_min_hot_entries = min_hot_entries
        return self

    def with_trace_inspect_max_chars(
        self,
        max_chars: int,
    ) -> "ContextEngineBuilder":
        if (
            isinstance(max_chars, bool)
            or not isinstance(max_chars, int)
            or max_chars < MIN_CONTINUATION_PAGE_CHARS
        ):
            raise ContextContractError(
                "Trace inspect max_chars must leave room for response metadata"
            )
        self._trace_inspect_max_chars = max_chars
        return self

    def with_compression_target_ratio(
        self,
        ratio: float,
    ) -> "ContextEngineBuilder":
        if not 0 < ratio < 1:
            raise ContextContractError(
                "Context compression target ratio must be between 0 and 1"
            )
        self._compression_target_ratio = ratio
        return self

    def with_compression_trigger_ratio(
        self,
        ratio: float,
    ) -> "ContextEngineBuilder":
        if not 0 < ratio < 1:
            raise ContextContractError(
                "Context compression trigger ratio must be between 0 and 1"
            )
        self._compression_trigger_ratio = ratio
        return self

    def with_segment(self, registration: RegisteredSegment) -> "ContextEngineBuilder":
        self._registrations.append(registration)
        return self

    def build(self) -> ContextEngine:
        if self._compression_target_ratio >= self._compression_trigger_ratio:
            raise ContextContractError(
                "Context compression target ratio must be below the trigger ratio"
            )
        return ContextEngine(
            system_text=self._system_text,
            composer=MessageStackComposer(
                budget=ContextBudget(
                    max_image_bytes=self._max_image_bytes,
                ),
            ),
            compressor=ContextCompressor(
                chunk_max_chars=self._trace_chunk_max_chars,
                branch_factor=self._trace_branch_factor,
                min_hot_entries=self._trace_min_hot_entries,
            ),
            journal=self._journal,
            registrations=tuple(self._registrations),
            trace_inspect_max_chars=self._trace_inspect_max_chars,
            compression_trigger_ratio=self._compression_trigger_ratio,
            compression_target_ratio=self._compression_target_ratio,
            observations=self._observations,
        )


def _signal_call_id(signal: Signal) -> str:
    call_id = signal.payload.get("call_id")
    if isinstance(call_id, str):
        return call_id
    return ""
