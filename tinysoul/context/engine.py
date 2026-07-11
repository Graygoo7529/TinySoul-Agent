"""Context module assembly facade."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from uuid import uuid4

from tinysoul.infra.json import JsonObject, JsonValue, to_json_object
from tinysoul.llm.messages import (
    AssistantMessage,
    JsonPart,
    Message,
    MessageStack,
    TextPart,
    ToolResultMessage,
    UserMessage,
)
from tinysoul.llm.tools import ToolCallRecord, ToolScope
from tinysoul.runtime import RunLevel, RunScope, Signal, SignalBus

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
    SIGNAL_WORKSPACE_SYNC,
    TraceAppend,
    parse_background_patch_signal,
    parse_input_append_signal,
    parse_trace_append_signal,
    parse_working_patch_signal,
    parse_workspace_sync_signal,
)
from .trace import CompressionReport, PendingInputs, TraceKind, TurnTraceContext
from .working import WorkingContext, WorkingPatch, WorkspaceSnapshot


@dataclass(frozen=True)
class TurnSummary:
    """A JSON-safe summary of one finished turn."""

    turn_id: str
    inputs: tuple[JsonObject, ...] = field(default_factory=tuple)
    working: JsonObject = field(default_factory=dict)
    background_links: tuple[str, ...] = field(default_factory=tuple)
    trace_digest: JsonObject = field(default_factory=dict)
    trace: tuple[JsonObject, ...] = field(default_factory=tuple)

    def to_json(self) -> JsonObject:
        return {
            "turn_id": self.turn_id,
            "inputs": list(self.inputs),
            "working": self.working,
            "background_links": list(self.background_links),
            "trace_digest": self.trace_digest,
            "trace": list(self.trace),
        }


class BackgroundContentLoader(Protocol):
    """Load one BackgroundContext entry at the moment it becomes visible."""

    def load(self) -> str:
        """Return non-empty entry content."""
        ...


@dataclass(frozen=True)
class StaticBackgroundContentLoader:
    """In-memory loader used for static or already-materialized content."""

    content: str

    def load(self) -> str:
        return self.content


@dataclass(frozen=True)
class ContextSignalBatch:
    """A replayable group of context signals owned by one active Turn."""

    turn_id: str
    signals: tuple[Signal, ...] = field(default_factory=tuple)


class ContextEngine:
    """Assembled context module entry point for loop integration."""

    def __init__(
        self,
        *,
        composer: MessageStackComposer,
        compressor: ContextCompressor,
        background: BackgroundContext,
        loadable_entries: dict[str, BackgroundContentLoader],
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
        return self._turn_id

    def compose(self, task_prompt: TaskPrompt) -> MessageStack:
        self._require_turn()
        return self._composer.compose(
            inputs=self._inputs,
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

    def take_signal_batch(self, bus: SignalBus) -> ContextSignalBatch:
        """Remove the current context namespace from the bus as a replayable batch."""

        self._require_turn()
        return ContextSignalBatch(
            turn_id=self._turn_id,
            signals=bus.consume_namespace(SIGNAL_NAMESPACE),
        )

    def consume_signals(self, bus: SignalBus) -> tuple[ControlResult, ...]:
        """Take and synchronously commit one context signal batch."""

        return self.consume_signal_batch(self.take_signal_batch(bus))

    def consume_signal_batch(
        self,
        batch: ContextSignalBatch,
    ) -> tuple[ControlResult, ...]:
        """Prepare and atomically commit a replayable context signal batch.

        Invalid signals become local results. Valid working/background patches are
        checked against a projected batch state. Lazy background content is fully
        loaded before the first state mutation, so a Runtime Trap can retry this
        exact batch without observing a partial commit.
        """

        self._require_turn()
        if batch.turn_id != self._turn_id:
            raise ContextContractError(
                "Context signal batch belongs to a different active Turn"
            )
        results: list[ControlResult] = []
        working_candidates: list[tuple[int, Signal, str, WorkingPatch]] = []
        workspace_candidates: list[tuple[int, Signal, str, WorkspaceSnapshot]] = []
        background_candidates: list[tuple[int, Signal, str, BackgroundPatch]] = []
        trace_appends: list[TraceAppend] = []
        input_texts: list[str] = []

        for index, signal in enumerate(batch.signals):
            sequence = index + 1
            scope_problem = self._signal_scope_problem(signal)
            if scope_problem:
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
                elif signal.name == SIGNAL_WORKSPACE_SYNC:
                    call_id, snapshot = parse_workspace_sync_signal(signal)
                    workspace_candidates.append(
                        (sequence, signal, call_id, snapshot)
                    )
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
        workspace_snapshots = self._validated_workspace_snapshots(
            workspace_candidates,
            results=results,
        )
        background_patches = self._validated_background_patches(
            background_candidates,
            results=results,
        )
        prepared_background = self._prepare_background(background_patches)

        for patch in working_patches:
            self._working.apply_patch(patch)
        for snapshot in workspace_snapshots:
            self._working.apply_workspace_snapshot(snapshot)
        for patch in background_patches:
            self._apply_background_patch(patch, prepared=prepared_background)
        for append in trace_appends:
            self._apply_trace_append(append)
        for text in input_texts:
            self._inputs.add(text)
        return tuple(sorted(results, key=lambda result: result.sequence))

    def merge_pending_inputs(self) -> int:
        self._require_turn()
        unmerged = self._inputs.unmerged()
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
            trace=_trace_records(self._trace),
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

    def _validated_workspace_snapshots(
        self,
        candidates: list[tuple[int, Signal, str, WorkspaceSnapshot]],
        *,
        results: list[ControlResult],
    ) -> tuple[WorkspaceSnapshot, ...]:
        snapshots = tuple(snapshot for _, _, _, snapshot in candidates)
        problems = self._working.check_workspace_sequence(snapshots)
        valid: list[WorkspaceSnapshot] = []
        for (sequence, signal, call_id, snapshot), problem in zip(
            candidates,
            problems,
        ):
            if problem:
                results.append(_consume_failure(signal, call_id, sequence, problem))
                continue
            valid.append(snapshot)
        return tuple(valid)

    def _prepare_background(
        self,
        patches: tuple[BackgroundPatch, ...],
    ) -> dict[str, str]:
        prepared: dict[str, str] = {}
        loaded = set(self._background.links())
        for patch in patches:
            for link in patch.load_links:
                if link in loaded:
                    continue
                content = prepared.get(link)
                if content is None:
                    content = self._loadable_entries[link].load()
                    if not content:
                        raise ContextContractError(
                            f"Background loader returned empty content: {link}"
                        )
                    prepared[link] = content
                loaded.add(link)
            for link in patch.evict_links:
                loaded.discard(link)
        return prepared

    def _apply_background_patch(
        self,
        patch: BackgroundPatch,
        *,
        prepared: dict[str, str],
    ) -> None:
        for link in patch.load_links:
            if self._background.has(link):
                continue
            self._background.load(
                BackgroundEntry(
                    link=link,
                    content=prepared[link],
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

    def __init__(self, *, system_text: str) -> None:
        if not system_text:
            raise ContextContractError("ContextEngineBuilder requires non-empty system text")
        self._system_text = system_text
        self._journal = ""
        self._max_chars: int | None = None
        self._max_image_bytes: int | None = None
        self._keep_recent = 12
        self._default_entries: list[BackgroundEntry] = []
        self._loadable_entries: dict[str, BackgroundContentLoader] = {}

    def with_journal(self, journal: str) -> "ContextEngineBuilder":
        self._journal = journal
        return self

    def with_budget_max_chars(self, max_chars: int | None) -> "ContextEngineBuilder":
        if max_chars is not None and max_chars <= 0:
            raise ContextContractError("Context budget max chars must be positive")
        self._max_chars = max_chars
        return self

    def with_budget_max_image_bytes(
        self,
        max_image_bytes: int | None,
    ) -> "ContextEngineBuilder":
        if max_image_bytes is not None and max_image_bytes <= 0:
            raise ContextContractError(
                "Context image byte budget must be positive"
            )
        self._max_image_bytes = max_image_bytes
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
        self._default_entries.append(
            BackgroundEntry(link=link, content=content, source=BackgroundSource.DEFAULT)
        )
        return self

    def add_loadable_background(self, link: str, content: str) -> "ContextEngineBuilder":
        if not link or not content:
            raise ContextContractError(
                "Loadable background entries require non-empty link and content"
            )
        return self.add_lazy_background(
            link,
            StaticBackgroundContentLoader(content),
        )

    def add_lazy_background(
        self,
        link: str,
        loader: BackgroundContentLoader,
    ) -> "ContextEngineBuilder":
        if not link:
            raise ContextContractError("Lazy background link must be non-empty")
        if link in self._loadable_entries:
            raise ContextContractError(f"Duplicate loadable background link: {link}")
        if not hasattr(loader, "load"):
            raise ContextContractError("Lazy background loader must provide load()")
        self._loadable_entries[link] = loader
        return self

    def build(self) -> ContextEngine:
        background = BackgroundContext(journal=self._journal)
        loadable = dict(self._loadable_entries)
        for entry in self._default_entries:
            background.load(entry)
            # Default entries are evictable and reloadable like Phase1-loaded ones.
            loadable.setdefault(
                entry.link,
                StaticBackgroundContentLoader(entry.content),
            )
        return ContextEngine(
            composer=MessageStackComposer(
                system_text=self._system_text,
                budget=ContextBudget(
                    max_chars=self._max_chars,
                    max_image_bytes=self._max_image_bytes,
                ),
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


def _trace_records(trace: TurnTraceContext) -> tuple[JsonObject, ...]:
    return tuple(
        {
            "entry_id": entry.entry_id,
            "kind": entry.kind.value,
            "cycle_id": entry.cycle_id,
            "phase": entry.phase.value if entry.phase is not None else "",
            "message": _message_record(entry.message),
        }
        for entry in trace.entries()
    )


def _message_record(message: Message) -> JsonObject:
    role = "user"
    if isinstance(message, AssistantMessage):
        role = "assistant"
    elif isinstance(message, ToolResultMessage):
        role = "tool_result"
    content: list[JsonValue] = []
    for part in message.parts:
        if isinstance(part, TextPart):
            content.append({"type": "text", "text": part.text})
        elif isinstance(part, JsonPart):
            content.append({"type": "json", "value": part.value})
    record: JsonObject = {
        "role": role,
        "label": message.label,
        "content": content,
    }
    if isinstance(message, AssistantMessage):
        if message.reasoning is not None:
            reasoning: JsonObject = {}
            if message.reasoning.content is not None:
                reasoning["content"] = message.reasoning.content
            if message.reasoning.summary is not None:
                reasoning["summary"] = message.reasoning.summary
            if message.reasoning.encrypted_items:
                reasoning["encrypted_items"] = [
                    to_json_object(item)
                    for item in message.reasoning.encrypted_items
                ]
            record["reasoning"] = reasoning
        record["tool_calls"] = [
            {
                "id": call.id,
                "name": call.name,
                "arguments": call.arguments,
                "kind": call.kind.value if call.kind is not None else "",
            }
            for call in message.tool_calls
        ]
    elif isinstance(message, ToolResultMessage):
        record["call_id"] = message.call_id
        record["tool_name"] = message.tool_name
        record["status"] = message.status.value
    elif not isinstance(message, UserMessage):
        record["role"] = "system"
    return to_json_object(record)


def _signal_call_id(signal: Signal) -> str:
    call_id = signal.payload.get("call_id")
    if isinstance(call_id, str):
        return call_id
    return ""
