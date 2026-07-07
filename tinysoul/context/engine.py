"""Context module assembly facade."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.llm.messages import MessageStack
from tinysoul.llm.tools import ToolCallRecord, ToolScope
from tinysoul.runtime import RunScope, Signal, SignalBus

from .background import (
    BackgroundContext,
    BackgroundEntry,
    BackgroundPatch,
    BackgroundSource,
)
from .composer import ContextBudget, MessageStackComposer
from .compress import ContextCompressor
from .controls import (
    ContextControlScopeBuilder,
    ControlCallNormalizer,
    ControlNormalization,
    ControlResult,
    ControlResultStage,
)
from .errors import ContextContractError
from .prompts import TaskPrompt
from .signals import (
    SIGNAL_BACKGROUND_PATCH,
    SIGNAL_INPUT_APPEND,
    SIGNAL_NAMESPACE,
    SIGNAL_TRACE_APPEND,
    SIGNAL_WORKING_PATCH,
    TraceAppend,
    parse_background_patch_signal,
    parse_input_append_signal,
    parse_trace_append_signal,
    parse_working_patch_signal,
)
from .trace import CompressionReport, PendingInputs, TraceKind, TurnTraceContext
from .working import WorkingContext, WorkingPatch


@dataclass(frozen=True)
class TurnSummary:
    """A JSON-safe summary of one finished turn."""

    turn_id: str
    inputs: tuple[JsonObject, ...] = field(default_factory=tuple)
    working: JsonObject = field(default_factory=dict)
    background_links: tuple[str, ...] = field(default_factory=tuple)
    trace_digest: JsonObject = field(default_factory=dict)

    def to_json(self) -> JsonObject:
        return {
            "turn_id": self.turn_id,
            "inputs": list(self.inputs),
            "working": self.working,
            "background_links": list(self.background_links),
            "trace_digest": self.trace_digest,
        }


class ContextEngine:
    """Assembled context module entry point for loop integration."""

    def __init__(
        self,
        *,
        composer: MessageStackComposer,
        compressor: ContextCompressor,
        background: BackgroundContext,
        loadable_entries: dict[str, str],
    ) -> None:
        self._composer = composer
        self._compressor = compressor
        self._background = background
        self._loadable_entries = dict(loadable_entries)
        self._scope_builder = ContextControlScopeBuilder()
        self._normalizer = ControlCallNormalizer()
        self._working = WorkingContext()
        self._trace = TurnTraceContext()
        self._inputs = PendingInputs()
        self._turn_id = ""

    @property
    def turn_active(self) -> bool:
        return bool(self._turn_id)

    def background_links(self) -> tuple[str, ...]:
        """Return currently loaded background links without exposing mutable state."""

        return self._background.links()

    def working_snapshot(self) -> JsonObject:
        """Return a JSON-safe copy of the working context."""

        self._require_turn()
        return to_json_object(self._working.to_json())

    def trace_kinds(self) -> tuple[TraceKind, ...]:
        """Return trace entry kinds for observation and tests."""

        self._require_turn()
        return tuple(entry.kind for entry in self._trace.entries())

    def trace_digest(self) -> JsonObject:
        """Return a JSON-safe digest of the current turn trace."""

        self._require_turn()
        return _trace_digest(self._trace)

    def begin_turn(self, user_input: str) -> str:
        if self._turn_id:
            raise ContextContractError("A turn is already active")
        if not user_input:
            raise ContextContractError("begin_turn requires non-empty user input")
        self._turn_id = f"turn_{uuid4().hex[:8]}"
        self._working = WorkingContext()
        self._trace = TurnTraceContext()
        self._inputs = PendingInputs()
        self._inputs.add(user_input, merged=True)
        self._trace.append_user_input(user_input)
        return self._turn_id

    def compose(self, task_prompt: TaskPrompt) -> MessageStack:
        self._require_turn()
        return self._composer.compose(
            background=self._background,
            working=self._working,
            trace=self._trace,
            task_prompt=task_prompt,
        )

    def control_scope(self) -> ToolScope:
        self._require_turn()
        loadable = tuple(
            link for link in self._loadable_entries if not self._background.has(link)
        )
        evictable = tuple(
            link
            for link in self._background.links()
            if link in self._loadable_entries
        )
        return self._scope_builder.build(
            loadable_links=loadable,
            loaded_links=evictable,
        )

    def normalize_controls(
        self,
        tool_calls: tuple[ToolCallRecord, ...],
        *,
        scope: RunScope,
    ) -> ControlNormalization:
        self._require_turn()
        return self._normalizer.normalize(tool_calls, scope=scope)

    def consume_signals(self, bus: SignalBus) -> tuple[ControlResult, ...]:
        """Consume context signals with parse-first, projected validation.

        Invalid signals become local results. Valid working/background patches are
        checked against a projected batch state before any state is committed.
        """

        self._require_turn()
        signals = bus.consume_namespace(SIGNAL_NAMESPACE)
        results: list[ControlResult] = []
        working_candidates: list[tuple[int, Signal, str, WorkingPatch]] = []
        background_candidates: list[tuple[int, Signal, str, BackgroundPatch]] = []
        trace_appends: list[TraceAppend] = []
        input_texts: list[str] = []

        for index, signal in enumerate(signals):
            sequence = index + 1
            try:
                if signal.name == SIGNAL_WORKING_PATCH:
                    call_id, patch = parse_working_patch_signal(signal)
                    working_candidates.append((sequence, signal, call_id, patch))
                elif signal.name == SIGNAL_BACKGROUND_PATCH:
                    call_id, patch = parse_background_patch_signal(signal)
                    background_candidates.append((sequence, signal, call_id, patch))
                elif signal.name == SIGNAL_TRACE_APPEND:
                    trace_appends.append(parse_trace_append_signal(signal))
                elif signal.name == SIGNAL_INPUT_APPEND:
                    input_texts.append(parse_input_append_signal(signal))
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

        working_patches = self._validated_working_patches(
            working_candidates,
            results=results,
        )
        background_patches = self._validated_background_patches(
            background_candidates,
            results=results,
        )

        for patch in working_patches:
            self._working.apply_patch(patch)
        for patch in background_patches:
            self._apply_background_patch(patch)
        for append in trace_appends:
            self._apply_trace_append(append)
        for text in input_texts:
            self._inputs.add(text)
        return tuple(sorted(results, key=lambda result: result.sequence))

    def merge_pending_inputs(self) -> int:
        self._require_turn()
        unmerged = self._inputs.unmerged()
        for item in unmerged:
            self._trace.append_user_input(item.text)
        self._inputs.mark_merged(tuple(item.input_id for item in unmerged))
        return len(unmerged)

    def compress(self) -> CompressionReport:
        self._require_turn()
        return self._compressor.compress(self._trace)

    def end_turn(self) -> TurnSummary:
        self._require_turn()
        trace_digest = _trace_digest(self._trace)
        summary = TurnSummary(
            turn_id=self._turn_id,
            inputs=tuple(
                {
                    "input_id": item.input_id,
                    "text": item.text,
                    "received_at": item.received_at,
                    "merged": item.merged,
                }
                for item in self._inputs.all()
            ),
            working=self._working.to_json(),
            background_links=self._background.links(),
            trace_digest=trace_digest,
        )
        self._turn_id = ""
        return summary

    def abort_turn(self) -> None:
        """Discard the active turn state when summary finalization cannot complete."""

        if not self._turn_id:
            return
        self._turn_id = ""
        self._working = WorkingContext()
        self._trace = TurnTraceContext()
        self._inputs = PendingInputs()

    def _validated_working_patches(
        self,
        candidates: list[tuple[int, Signal, str, WorkingPatch]],
        *,
        results: list[ControlResult],
    ) -> tuple[WorkingPatch, ...]:
        patches = tuple(patch for _, _, _, patch in candidates)
        problems = self._working.check_patch_sequence(patches)
        valid: list[WorkingPatch] = []
        for (sequence, signal, call_id, patch), problem in zip(candidates, problems):
            if problem:
                results.append(_consume_failure(signal, call_id, sequence, problem))
                continue
            valid.append(patch)
        return tuple(valid)

    def _validated_background_patches(
        self,
        candidates: list[tuple[int, Signal, str, BackgroundPatch]],
        *,
        results: list[ControlResult],
    ) -> tuple[BackgroundPatch, ...]:
        patches = tuple(patch for _, _, _, patch in candidates)
        problems = self._background.check_patch_sequence(
            patches,
            loadable_links=tuple(self._loadable_entries),
        )
        valid: list[BackgroundPatch] = []
        for (sequence, signal, call_id, patch), problem in zip(candidates, problems):
            if problem:
                results.append(_consume_failure(signal, call_id, sequence, problem))
                continue
            valid.append(patch)
        return tuple(valid)

    def _apply_background_patch(self, patch: BackgroundPatch) -> None:
        for link in patch.load_links:
            if self._background.has(link):
                continue
            self._background.load(
                BackgroundEntry(
                    link=link,
                    content=self._loadable_entries[link],
                    source=BackgroundSource.PHASE1,
                )
            )
        for link in patch.evict_links:
            self._background.evict(link)

    def _apply_trace_append(self, append: TraceAppend) -> None:
        if append.decision is not None:
            self._trace.append_decision(
                append.decision,
                cycle_id=append.cycle_id,
                phase=append.phase,
            )
        elif append.action_result is not None:
            self._trace.append_action_result(
                append.action_result,
                cycle_id=append.cycle_id,
            )
        elif append.note is not None:
            self._trace.append_phase_note(
                append.note,
                cycle_id=append.cycle_id,
                phase=append.phase,
            )

    def _require_turn(self) -> None:
        if not self._turn_id:
            raise ContextContractError("No active turn")


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

    def __init__(self, *, system_text: str) -> None:
        if not system_text:
            raise ContextContractError("ContextEngineBuilder requires non-empty system text")
        self._system_text = system_text
        self._journal = ""
        self._max_chars: int | None = None
        self._keep_recent = 12
        self._default_entries: list[BackgroundEntry] = []
        self._loadable_entries: dict[str, str] = {}

    def with_journal(self, journal: str) -> "ContextEngineBuilder":
        self._journal = journal
        return self

    def with_budget_max_chars(self, max_chars: int | None) -> "ContextEngineBuilder":
        if max_chars is not None and max_chars <= 0:
            raise ContextContractError("Context budget max chars must be positive")
        self._max_chars = max_chars
        return self

    def with_keep_recent(self, keep_recent: int) -> "ContextEngineBuilder":
        if keep_recent < 0:
            raise ContextContractError("Context keep_recent cannot be negative")
        self._keep_recent = keep_recent
        return self

    def add_default_background(self, link: str, content: str) -> "ContextEngineBuilder":
        if not link or not content:
            raise ContextContractError(
                "Default background entries require non-empty link and content"
            )
        for entry in self._default_entries:
            if entry.link == link:
                raise ContextContractError(f"Duplicate default background link: {link}")
        loadable_content = self._loadable_entries.get(link)
        if loadable_content is not None and loadable_content != content:
            raise ContextContractError(
                f"Default background content conflicts with loadable link: {link}"
            )
        self._default_entries.append(
            BackgroundEntry(link=link, content=content, source=BackgroundSource.DEFAULT)
        )
        return self

    def add_loadable_background(self, link: str, content: str) -> "ContextEngineBuilder":
        if not link or not content:
            raise ContextContractError(
                "Loadable background entries require non-empty link and content"
            )
        if link in self._loadable_entries:
            raise ContextContractError(f"Duplicate loadable background link: {link}")
        for entry in self._default_entries:
            if entry.link == link and entry.content != content:
                raise ContextContractError(
                    f"Loadable background content conflicts with default link: {link}"
                )
        self._loadable_entries[link] = content
        return self

    def build(self) -> ContextEngine:
        background = BackgroundContext(journal=self._journal)
        loadable = dict(self._loadable_entries)
        for entry in self._default_entries:
            background.load(entry)
            # Default entries are evictable and reloadable like Phase1-loaded ones.
            loadable.setdefault(entry.link, entry.content)
        return ContextEngine(
            composer=MessageStackComposer(
                system_text=self._system_text,
                budget=ContextBudget(max_chars=self._max_chars),
            ),
            compressor=ContextCompressor(keep_recent=self._keep_recent),
            background=background,
            loadable_entries=loadable,
        )


def _trace_digest(trace: TurnTraceContext) -> JsonObject:
    entries = trace.entries()
    return to_json_object(
        {
            "entry_count": len(entries),
            "kinds": sorted({entry.kind.value for entry in entries}),
        }
    )


def _signal_call_id(signal: Signal) -> str:
    call_id = signal.payload.get("call_id")
    if isinstance(call_id, str):
        return call_id
    return ""
