"""Context module assembly facade."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
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
    SessionBackgroundSnapshot,
)
from .composer import ContextBudget, MessageStackComposer
from .compress import ContextCompressor, ContextPressureReport
from .controls import (
    ContextControlScopeBuilder,
    ControlCallNormalizer,
    ControlNormalization,
    ControlResult,
    ControlResultStage,
)
from .errors import ContextContractError, ContextInvariantError
from .prompts import TaskPrompt
from .providers import (
    BackgroundCatalog,
    BackgroundEntryProvider,
)
from .signals import (
    SIGNAL_BACKGROUND_PATCH,
    SIGNAL_INPUT_APPEND,
    SIGNAL_NAMESPACE,
    SIGNAL_SESSION_SYNC,
    SIGNAL_TRACE_APPEND,
    SIGNAL_WORKING_PATCH,
    SIGNAL_WORKSPACE_SYNC,
    TraceAppend,
    parse_background_patch_signal,
    parse_input_append_signal,
    parse_session_sync_signal,
    parse_trace_append_signal,
    parse_working_patch_signal,
    parse_workspace_sync_signal,
)
from .trace import (
    PendingInputs,
    SealedTurnTrace,
    TraceCompactionReport,
    TraceEntry,
    TraceKind,
    TurnTraceHeap,
)
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
    trace_heap: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.turn_id:
            raise ContextContractError("TurnSummary.turn_id must be non-empty")
        object.__setattr__(
            self,
            "inputs",
            tuple(to_json_object(item) for item in self.inputs),
        )
        object.__setattr__(self, "working", to_json_object(self.working))
        links = tuple(self.background_links)
        if any(not isinstance(link, str) or not link for link in links):
            raise ContextContractError(
                "TurnSummary.background_links must contain non-empty strings"
            )
        if len(set(links)) != len(links):
            raise ContextContractError("TurnSummary.background_links must be unique")
        object.__setattr__(self, "background_links", links)
        object.__setattr__(
            self,
            "trace_digest",
            to_json_object(self.trace_digest),
        )
        object.__setattr__(
            self,
            "trace",
            tuple(to_json_object(item) for item in self.trace),
        )
        object.__setattr__(self, "trace_heap", to_json_object(self.trace_heap))

    def to_json(self) -> JsonObject:
        return {
            "turn_id": self.turn_id,
            "inputs": list(self.inputs),
            "working": self.working,
            "background_links": list(self.background_links),
            "trace_digest": self.trace_digest,
            "trace": list(self.trace),
            "trace_heap": self.trace_heap,
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
        compressor: ContextCompressor,
        background: BackgroundContext,
        default_entries: tuple[BackgroundEntry, ...],
        loadable_entries: dict[str, BackgroundContentLoader],
        background_providers: tuple[BackgroundEntryProvider, ...],
        trace_recall_max_chars: int,
        compression_target_ratio: float,
    ) -> None:
        self._composer = composer
        self._compressor = compressor
        self._background = background
        self._default_entries = tuple(default_entries)
        self._loadable_entries = dict(loadable_entries)
        self._background_providers = tuple(background_providers)
        self._provider_by_link: dict[str, BackgroundEntryProvider] = {}
        self._provider_by_owner: dict[str, BackgroundEntryProvider] = {}
        self._catalog_by_owner: dict[str, BackgroundCatalog] = {}
        self._business_day: date | None = None
        self._trace_recall_max_chars = trace_recall_max_chars
        self._compression_target_ratio = compression_target_ratio
        self._scope_builder = ContextControlScopeBuilder()
        self._normalizer = ControlCallNormalizer()
        self._working = WorkingContext()
        self._trace = compressor.new_trace("detached")
        self._inputs = PendingInputs()
        self._turn_id = ""
        self._preparing_turn = False

    @property
    def turn_active(self) -> bool:
        return bool(self._turn_id)

    @property
    def compression_target_ratio(self) -> float:
        return self._compression_target_ratio

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
        self._trace = self._compressor.new_trace(self._turn_id)
        self._inputs = PendingInputs()
        self._inputs.add(user_input, merged=True)
        self._background.reset_entries()
        self._background.reset_session()
        self._background.reset_catalogs()
        self._provider_by_link = {}
        self._provider_by_owner = {}
        self._catalog_by_owner = {}
        self._business_day = None
        self._preparing_turn = True
        return self._turn_id

    def prepare_default_background(self, business_day: date) -> None:
        """Load all provider defaults for one captured Business Day."""

        self._require_turn()
        if not isinstance(business_day, date):
            raise ContextContractError("Background preparation requires a date")
        self._business_day = business_day
        catalogs = self._collect_background_catalogs(business_day)
        self._background.reset_catalogs(catalogs)
        entries = list(self._default_entries)
        seen = {entry.link for entry in entries}
        for catalog in catalogs:
            provider = self._provider_for_owner(catalog.owner)
            for link in catalog.default_links:
                if link in seen:
                    raise ContextInvariantError(
                        f"Duplicate default Background link: {link}"
                    )
                content = provider.load(link, business_day)
                if not content:
                    raise ContextInvariantError(
                        f"Background provider returned empty content: {link}"
                    )
                evictable = link in catalog.evictable_default_links
                entries.append(
                    BackgroundEntry(
                        link=link,
                        content=content,
                        source=(
                            BackgroundSource.AUTOMATIC
                            if evictable
                            else BackgroundSource.DEFAULT
                        ),
                        owner=catalog.owner,
                        evictable=evictable,
                    )
                )
                seen.add(link)
        self._background.reset_entries(tuple(entries))

    def complete_preparation(self) -> None:
        self._require_turn()
        self._preparing_turn = False

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
        loadable_links = self._all_loadable_links()
        loadable = tuple(
            link for link in loadable_links if not self._background.has(link)
        )
        evictable = self._background.evictable_links()
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
        session_candidates: list[
            tuple[int, Signal, str, SessionBackgroundSnapshot]
        ] = []
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
                elif signal.name == SIGNAL_SESSION_SYNC:
                    if not self._preparing_turn:
                        raise ContextContractError(
                            "Session background can only be synchronized during Turn preparation"
                        )
                    call_id, snapshot = parse_session_sync_signal(signal)
                    session_candidates.append(
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
        session_snapshots = self._validated_session_snapshots(
            session_candidates,
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
        for snapshot in session_snapshots:
            self._background.apply_session_snapshot(snapshot)
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

    def compress(self, *, required_chars: int = 1) -> TraceCompactionReport:
        self._require_turn()
        return self._compressor.compress(
            self._trace,
            required_chars=required_chars,
        )

    def reclaim_pressure(self, *, required_chars: int) -> ContextPressureReport:
        self._require_turn()
        trace_report = self._compressor.compress(
            self._trace,
            required_chars=max(0, required_chars),
        )
        remaining = max(0, required_chars - trace_report.reclaimed_chars)
        background_report = self._background.evict_for_budget(
            required_chars=remaining
        )
        return ContextPressureReport(
            changed=trace_report.changed or background_report.changed,
            reclaimed_chars=(
                trace_report.reclaimed_chars + background_report.reclaimed_chars
            ),
            trace=trace_report,
            evicted_background_links=background_report.evicted_links,
        )

    def inspect_trace(self, ref: str) -> JsonObject:
        self._require_turn()
        return self._trace.inspect(ref)

    def recall_trace(
        self,
        ref: str,
        *,
        max_chars: int | None = None,
        cursor: int = 0,
    ) -> JsonObject:
        self._require_turn()
        if max_chars is not None and (
            isinstance(max_chars, bool) or max_chars <= 0
        ):
            raise ContextContractError("Trace recall max_chars must be positive")
        if isinstance(cursor, bool) or cursor < 0:
            raise ContextContractError("Trace recall cursor cannot be negative")
        limit = (
            self._trace_recall_max_chars
            if max_chars is None
            else min(max_chars, self._trace_recall_max_chars)
        )
        page = self._trace.recall(ref, max_chars=limit, cursor=cursor)
        return to_json_object(
            {
                "origin_ref": ref,
                "cursor": page.cursor,
                "next_cursor": page.next_cursor,
                "truncated": page.truncated,
                "entry_count": len(page.entries),
                "entries": [_trace_entry_record(entry) for entry in page.entries],
            }
        )

    def fold_trace_recalls(self) -> int:
        self._require_turn()
        return self._trace.fold_recalls()

    def seal_trace(self) -> SealedTurnTrace:
        self._require_turn()
        return self._trace.seal()

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
            trace_heap=_trace_heap_record(self._trace.seal()),
        )
        self._turn_id = ""
        self._preparing_turn = False
        return summary

    def abort_turn(self) -> None:
        """Discard the active turn state when summary finalization cannot complete."""

        if not self._turn_id:
            return
        self._turn_id = ""
        self._working = WorkingContext()
        self._trace = self._compressor.new_trace("detached")
        self._inputs = PendingInputs()
        self._background.reset_entries()
        self._background.reset_session()
        self._background.reset_catalogs()
        self._provider_by_link = {}
        self._provider_by_owner = {}
        self._catalog_by_owner = {}
        self._business_day = None
        self._preparing_turn = False

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
        non_evictable_loaded = set(self._background.links()).difference(
            self._background.evictable_links()
        )
        protected_defaults = {
            link
            for catalog in self._catalog_by_owner.values()
            for link in catalog.default_links
            if link not in catalog.evictable_default_links
        }
        evictable_links = tuple(
            link
            for link in self._all_loadable_links()
            if link not in non_evictable_loaded and link not in protected_defaults
        )
        problems = self._background.check_patch_sequence(
            patches,
            loadable_links=self._all_loadable_links(),
            evictable_links=evictable_links,
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

    def _validated_session_snapshots(
        self,
        candidates: list[tuple[int, Signal, str, SessionBackgroundSnapshot]],
        *,
        results: list[ControlResult],
    ) -> tuple[SessionBackgroundSnapshot, ...]:
        if len(candidates) > 1:
            for sequence, signal, call_id, _ in candidates:
                results.append(
                    _consume_failure(
                        signal,
                        call_id,
                        sequence,
                        "A preparation batch may contain only one Session snapshot",
                    )
                )
            return ()
        valid: list[SessionBackgroundSnapshot] = []
        for sequence, signal, call_id, snapshot in candidates:
            problem = self._background.check_session_snapshot(snapshot)
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
                    content = self._load_background(link)
                    if not content:
                        raise ContextContractError(
                            f"Background loader returned empty content: {link}"
                        )
                    prepared[link] = content
                loaded.add(link)
            for link in patch.evict_links:
                loaded.discard(link)
        return prepared

    def _collect_background_catalogs(
        self,
        business_day: date,
    ) -> tuple[BackgroundCatalog, ...]:
        catalogs: list[BackgroundCatalog] = []
        links = set(self._loadable_entries)
        owners: set[str] = set()
        self._provider_by_link = {}
        self._provider_by_owner = {}
        self._catalog_by_owner = {}
        for provider in self._background_providers:
            catalog = provider.catalog(business_day)
            if not isinstance(catalog, BackgroundCatalog):
                raise ContextInvariantError(
                    "Background provider returned an invalid catalog"
                )
            if catalog.owner in owners:
                raise ContextInvariantError(
                    f"Duplicate Background provider owner: {catalog.owner}"
                )
            duplicates = links.intersection(catalog.loadable_links)
            if duplicates:
                raise ContextInvariantError(
                    f"Duplicate Background link: {sorted(duplicates)[0]}"
                )
            owners.add(catalog.owner)
            links.update(catalog.loadable_links)
            self._catalog_by_owner[catalog.owner] = catalog
            self._provider_by_owner[catalog.owner] = provider
            for link in catalog.loadable_links:
                self._provider_by_link[link] = provider
            catalogs.append(catalog)
        return tuple(catalogs)

    def _provider_for_owner(self, owner: str) -> BackgroundEntryProvider:
        provider = self._provider_by_owner.get(owner)
        if provider is None:
            raise ContextInvariantError(f"Unknown Background provider owner: {owner}")
        return provider

    def _all_loadable_links(self) -> tuple[str, ...]:
        return (*self._loadable_entries, *self._provider_by_link)

    def _load_background(self, link: str) -> str:
        loader = self._loadable_entries.get(link)
        if loader is not None:
            return loader.load()
        provider = self._provider_by_link.get(link)
        if provider is None:
            raise ContextInvariantError(f"Unknown Background link: {link}")
        if self._business_day is None:
            raise ContextInvariantError("Background providers are not prepared")
        return provider.load(link, self._business_day)

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
                    owner=self._owner_for_link(link),
                    evictable=True,
                )
            )
        for link in patch.evict_links:
            self._background.evict(link)

    def _owner_for_link(self, link: str) -> str:
        if link in self._loadable_entries:
            return "context"
        for owner, catalog in self._catalog_by_owner.items():
            if link in catalog.loadable_links:
                return owner
        raise ContextInvariantError(f"Unknown Background link owner: {link}")

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
                compact_message=append.compact_action_result,
                origin_ref=append.origin_ref,
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
        self._trace_chunk_max_chars = 12000
        self._trace_branch_factor = 4
        self._trace_min_hot_entries = 2
        self._trace_recall_max_chars = 8000
        self._compression_target_ratio = 0.80
        self._default_entries: list[BackgroundEntry] = []
        self._loadable_entries: dict[str, BackgroundContentLoader] = {}
        self._background_providers: list[BackgroundEntryProvider] = []

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

    def with_trace_recall_max_chars(
        self,
        max_chars: int,
    ) -> "ContextEngineBuilder":
        if max_chars <= 0:
            raise ContextContractError("Trace recall max_chars must be positive")
        self._trace_recall_max_chars = max_chars
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

    def add_default_background(self, link: str, content: str) -> "ContextEngineBuilder":
        if not link or not content:
            raise ContextContractError(
                "Default background entries require non-empty link and content"
            )
        for entry in self._default_entries:
            if entry.link == link:
                raise ContextContractError(f"Duplicate default background link: {link}")
        self._default_entries.append(
            BackgroundEntry(
                link=link,
                content=content,
                source=BackgroundSource.DEFAULT,
                evictable=True,
            )
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

    def add_background_provider(
        self,
        provider: BackgroundEntryProvider,
    ) -> "ContextEngineBuilder":
        if not hasattr(provider, "catalog") or not hasattr(provider, "load"):
            raise ContextContractError(
                "Background provider must provide catalog() and load()"
            )
        self._background_providers.append(provider)
        return self

    def build(self) -> ContextEngine:
        background = BackgroundContext(journal=self._journal)
        loadable = dict(self._loadable_entries)
        for entry in self._default_entries:
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
            compressor=ContextCompressor(
                chunk_max_chars=self._trace_chunk_max_chars,
                branch_factor=self._trace_branch_factor,
                min_hot_entries=self._trace_min_hot_entries,
            ),
            background=background,
            default_entries=tuple(self._default_entries),
            loadable_entries=loadable,
            background_providers=tuple(self._background_providers),
            trace_recall_max_chars=self._trace_recall_max_chars,
            compression_target_ratio=self._compression_target_ratio,
        )


def _trace_digest(trace: TurnTraceHeap) -> JsonObject:
    entries = trace.entries()
    action_names = sorted(
        {
            name
            for entry in entries
            for name in _message_action_names(entry.message)
        }
    )
    return to_json_object(
        {
            "entry_count": len(entries),
            "kinds": sorted({entry.kind.value for entry in entries}),
            "cycle_count": len({entry.cycle_id for entry in entries if entry.cycle_id}),
            "action_names": action_names,
        }
    )


def _message_action_names(message: Message) -> tuple[str, ...]:
    if isinstance(message, AssistantMessage):
        return tuple(call.name for call in message.tool_calls)
    if isinstance(message, ToolResultMessage):
        return (message.tool_name,)
    return ()


def _trace_records(trace: TurnTraceHeap) -> tuple[JsonObject, ...]:
    return tuple(
        _trace_entry_record(entry)
        for entry in trace.entries()
    )


def _trace_heap_record(trace: SealedTurnTrace) -> JsonObject:
    return to_json_object(
        {
            "turn_id": trace.turn_id,
            "head_ref": f"turn:trace@{trace.turn_id}",
            "root_ids": list(trace.root_ids),
            "nodes": [
                {
                    "node_id": node.node_id,
                    "kind": node.kind.value,
                    "level": node.level,
                    "entry_ids": list(node.entry_ids),
                    "child_ids": list(node.child_ids),
                    "cycle_ids": list(node.cycle_ids),
                    "trace_kinds": list(node.trace_kinds),
                    "action_names": list(node.action_names),
                    "char_count": node.char_count,
                }
                for node in trace.nodes
            ],
        }
    )


def _trace_entry_record(entry: TraceEntry) -> JsonObject:
    return to_json_object(
        {
            "entry_id": entry.entry_id,
            "kind": entry.kind.value,
            "cycle_id": entry.cycle_id,
            "phase": entry.phase.value if entry.phase is not None else "",
            "message": _message_record(entry.message),
            "origin_ref": entry.origin_ref,
        }
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
