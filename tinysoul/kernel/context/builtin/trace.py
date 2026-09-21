"""Turn trace heap and pending user inputs."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from time import time
from uuid import uuid4

from tinysoul.kernel.action.call import ActionCall, ExecutionFact, ExecutionState
from tinysoul.kernel.action.result import ActionResult

from tinysoul.infra.json import JsonObject, JsonValue, dumps_json, to_json_object
from tinysoul.llm.protocol.tools import ToolKind
from tinysoul.llm.protocol.messages import (
    AssistantMessage,
    JsonPart,
    Message,
    TextPart,
    ToolResultMessage,
    UserMessage,
)
from tinysoul.runtime import CyclePhase

from ..errors import (
    ContextContractError,
    ContextInvariantError,
    ContextInspectFailureReason,
    ContextInspectRequestError,
)


class TraceKind(StrEnum):
    """Kinds of canonical turn trace entries."""

    DECISION = "decision"
    ACTION_RESULT = "action_result"
    PHASE_NOTE = "phase_note"


class TraceFactKind(StrEnum):
    """Owner-observed order, never a claim about external causal time."""

    INPUT_INSTALLED = "input_installed"
    INPUT_VISIBLE = "input_visible"
    ACTION_REQUESTED = "action_requested"
    ACTION_STARTED = "action_started"
    ACTION_SETTLED = "action_settled"
    ACTION_CANCELLED = "action_cancelled"
    ACTION_NOT_EXECUTED = "action_not_executed"
    ACTION_UNKNOWN = "action_unknown"
    ENTRY = "entry"


@dataclass(frozen=True)
class TraceFact:
    sequence: int
    kind: TraceFactKind
    ref: str
    cycle_id: str = ""
    admission_sequence: int | None = None

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence <= 0:
            raise ContextInvariantError("Trace fact sequence must be positive")
        if not isinstance(self.kind, TraceFactKind) or not self.ref:
            raise ContextInvariantError("Trace fact requires a kind and reference")
        if self.admission_sequence is not None and (
            type(self.admission_sequence) is not int or self.admission_sequence <= 0
        ):
            raise ContextInvariantError("Admission sequence must be positive")


class TraceHeapNodeKind(StrEnum):
    """Kinds of immutable nodes in the compressed trace hierarchy."""

    LEAF = "leaf"
    BRANCH = "branch"


@dataclass(frozen=True)
class TraceEntry:
    """One canonical trace record plus an optional foldable visible overlay."""

    entry_id: str
    kind: TraceKind
    message: Message
    cycle_id: str = ""
    phase: CyclePhase | None = None
    visible_overlay: Message | None = None
    origin_refs: tuple[str, ...] = field(default_factory=tuple)
    admission_sequence: int | None = None

    def __post_init__(self) -> None:
        if not self.entry_id:
            raise ContextInvariantError("TraceEntry.entry_id must be non-empty")
        if not isinstance(self.kind, TraceKind):
            raise ContextInvariantError("TraceEntry.kind must be a TraceKind")
        if self.phase is not None and not isinstance(self.phase, CyclePhase):
            raise ContextInvariantError("TraceEntry.phase must be a CyclePhase")
        if any(not isinstance(ref, str) or not ref for ref in self.origin_refs):
            raise ContextInvariantError(
                "TraceEntry origin_refs must contain non-empty strings"
            )
        if len(set(self.origin_refs)) != len(self.origin_refs):
            raise ContextInvariantError("TraceEntry origin_refs must be unique")

    @property
    def visible_message(self) -> Message:
        return self.visible_overlay or self.message

    def to_semantic(self) -> JsonObject:
        return _semantic_trace_entry(self)


@dataclass(frozen=True)
class TraceHeapNode:
    """One immutable trace heap node."""

    node_id: str
    kind: TraceHeapNodeKind
    level: int
    entry_ids: tuple[str, ...] = field(default_factory=tuple)
    child_ids: tuple[str, ...] = field(default_factory=tuple)
    cycle_ids: tuple[str, ...] = field(default_factory=tuple)
    trace_kinds: tuple[str, ...] = field(default_factory=tuple)
    action_names: tuple[str, ...] = field(default_factory=tuple)
    char_count: int = 0

    def __post_init__(self) -> None:
        if not self.node_id:
            raise ContextInvariantError("TraceHeapNode.node_id must be non-empty")
        if not isinstance(self.kind, TraceHeapNodeKind):
            raise ContextInvariantError(
                "TraceHeapNode.kind must be a TraceHeapNodeKind"
            )
        if self.level < 0:
            raise ContextInvariantError("TraceHeapNode.level cannot be negative")
        if self.char_count < 0:
            raise ContextInvariantError("TraceHeapNode.char_count cannot be negative")
        if self.kind is TraceHeapNodeKind.LEAF:
            if not self.entry_ids or self.child_ids:
                raise ContextInvariantError(
                    "A leaf TraceHeapNode requires entries and no children"
                )
        elif not self.child_ids or self.entry_ids:
            raise ContextInvariantError(
                "A branch TraceHeapNode requires children and no entries"
            )

    def to_header(self, *, turn_id: str) -> JsonObject:
        value: JsonObject = {
            "ref": _node_ref(turn_id, self.node_id),
            "kind": self.kind.value,
        }
        if self.kind is TraceHeapNodeKind.LEAF:
            value["interaction_count"] = len(self.entry_ids)
        else:
            value["child_count"] = len(self.child_ids)
        if self.trace_kinds:
            value["interaction_kinds"] = list(self.trace_kinds)
        if self.action_names:
            value["actions"] = list(self.action_names)
        return to_json_object(value)


@dataclass(frozen=True)
class TraceCompactionReport:
    """Result of one lossless trace compaction pass."""

    changed: bool
    compacted_count: int
    folded_overlay_count: int
    reclaimed_chars: int
    remaining_hot_count: int
    node_refs: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TraceAction:
    """One call's canonical facts, keyed by Cycle and call sequence."""

    cycle_id: str
    call: ActionCall
    state: ExecutionState = ExecutionState.REQUESTED
    invoke_id: str | None = None
    result: ActionResult | None = None

    def __post_init__(self) -> None:
        if not self.cycle_id or not isinstance(self.call, ActionCall):
            raise ContextInvariantError("Trace Action requires Cycle and call identity")
        if not isinstance(self.state, ExecutionState):
            raise ContextInvariantError("Trace Action requires an execution state")
        if (self.state is ExecutionState.SETTLED) != (self.result is not None):
            raise ContextInvariantError("Only settled Trace Actions contain a result")
        if self.result is not None and not isinstance(self.result, ActionResult):
            raise ContextInvariantError("Trace Action requires a typed result")
        if self.result is not None and (
            self.result.call_id != self.call.call_id
            or self.result.action_name != self.call.action_name
            or self.result.sequence != self.call.sequence
            or self.result.invoke_id != self.invoke_id
        ):
            raise ContextInvariantError("Trace Action result identity does not match")


@dataclass(frozen=True)
class SealedTurnTrace:
    """Immutable canonical entries transferred once at Turn completion."""

    turn_id: str
    entries: tuple[TraceEntry, ...]
    actions: tuple[TraceAction, ...] = field(default=(), repr=False)
    timeline: tuple[TraceFact, ...] = ()

    def __post_init__(self) -> None:
        if not self.turn_id:
            raise ContextInvariantError("SealedTurnTrace.turn_id must be non-empty")
        if any(
            not isinstance(item, TraceFact) or item.sequence != index
            for index, item in enumerate(self.timeline, start=1)
        ):
            raise ContextInvariantError("Sealed Trace requires ordered fact references")
        if any(not isinstance(item, TraceAction) for item in self.actions):
            raise ContextInvariantError("Sealed Trace requires typed Action facts")
        identities = {(item.cycle_id, item.call.sequence) for item in self.actions}
        if len(identities) != len(self.actions):
            raise ContextInvariantError(
                "Sealed Trace contains duplicate Action identities"
            )
        if any(
            item.state in {ExecutionState.REQUESTED, ExecutionState.STARTED}
            for item in self.actions
        ):
            raise ContextInvariantError("Sealed Trace contains unsettled Actions")


class TurnTraceHeap:
    """Append-only canonical trace with a compact, recoverable visible hierarchy."""

    def __init__(
        self,
        *,
        turn_id: str = "detached",
        chunk_max_chars: int = 12000,
        branch_factor: int = 4,
        min_hot_entries: int = 2,
    ) -> None:
        if not turn_id:
            raise ContextContractError("TurnTraceHeap.turn_id must be non-empty")
        if chunk_max_chars <= 0:
            raise ContextContractError("TurnTraceHeap.chunk_max_chars must be positive")
        if branch_factor < 2:
            raise ContextContractError("TurnTraceHeap.branch_factor must be at least 2")
        if min_hot_entries < 0:
            raise ContextContractError(
                "TurnTraceHeap.min_hot_entries cannot be negative"
            )
        self._turn_id = turn_id
        self._chunk_max_chars = chunk_max_chars
        self._branch_factor = branch_factor
        self._min_hot_entries = min_hot_entries
        self._entries: list[TraceEntry] = []
        self._hot_entry_ids: list[str] = []
        self._nodes: dict[str, TraceHeapNode] = {}
        self._root_ids: list[str] = []
        self._actions: dict[tuple[str, int], TraceAction] = {}
        self._timeline: list[TraceFact] = []
        self._protected_overlays: set[str] = set()

    def record_fact(
        self,
        kind: TraceFactKind,
        ref: str,
        *,
        cycle_id: str = "",
        admission_sequence: int | None = None,
    ) -> None:
        self._timeline.append(
            TraceFact(len(self._timeline) + 1, kind, ref, cycle_id, admission_sequence)
        )

    def timeline(self) -> tuple[TraceFact, ...]:
        return tuple(self._timeline)

    def actions(self) -> tuple[TraceAction, ...]:
        """Read canonical request order without settling or sealing any call."""
        return tuple(self._actions.values())

    def action_ref(self, cycle_id: str, sequence: int) -> str:
        occurrence = tuple(self._actions).index((cycle_id, sequence))
        return f"{self.head_ref()}#action/{occurrence}"

    def entry_ref(self, entry_id: str) -> str:
        return f"{self.head_ref()}#entry/{entry_id}"

    def input_ref(self, input_id: str) -> str:
        return f"{self.head_ref()}#input/{input_id}"

    def mark_consumed(self, messages: tuple[Message, ...]) -> None:
        """Release only overlays present in a completed decision-model request."""
        for entry in self.hot_entries():
            if entry.visible_overlay is not None and entry.visible_overlay in messages:
                self._protected_overlays.discard(entry.entry_id)

    def register_action_calls(
        self, calls: tuple[ActionCall, ...], *, cycle_id: str
    ) -> None:
        for call in calls:
            key = (cycle_id, call.sequence)
            previous = self._actions.get(key)
            if previous is not None:
                if previous.call != call:
                    raise ContextInvariantError("Trace Action call identity changed")
                continue
            self._actions[key] = TraceAction(cycle_id=cycle_id, call=call)
            self.record_fact(
                TraceFactKind.ACTION_REQUESTED, self.action_ref(*key), cycle_id=cycle_id
            )

    def record_action_result(self, result: ActionResult, *, cycle_id: str) -> None:
        key = (cycle_id, result.sequence)
        previous = self._actions.get(key)
        if previous is None:
            raise ContextInvariantError("Action result has no registered call")
        if previous.invoke_id is not None and previous.invoke_id != result.invoke_id:
            raise ContextInvariantError("Action result invocation identity changed")
        candidate = replace(
            previous,
            state=ExecutionState.SETTLED,
            invoke_id=result.invoke_id,
            result=result,
        )
        if previous == candidate:
            return
        if previous.state not in {ExecutionState.REQUESTED, ExecutionState.STARTED}:
            raise ContextInvariantError("Settled Action facts cannot change")
        self._actions[key] = candidate
        self.record_fact(
            TraceFactKind.ACTION_SETTLED, self.action_ref(*key), cycle_id=cycle_id
        )

    def record_execution(self, fact: ExecutionFact) -> None:
        """Accept execution facts independently of model-view preparation."""
        if fact.framework.turn_id != self._turn_id:
            raise ContextInvariantError("Execution fact belongs to another Turn")
        key = (fact.framework.cycle_id, fact.call.sequence)
        previous = self._actions.get(key)
        if previous is None or previous.call != fact.call:
            raise ContextInvariantError("Execution must reference its registered call")
        candidate = replace(
            previous,
            state=fact.state,
            invoke_id=fact.framework.invoke_id,
            result=fact.result,
        )
        if previous == candidate:
            return
        if previous.invoke_id and previous.invoke_id != candidate.invoke_id:
            raise ContextInvariantError("Action invocation identity changed")
        transitions = {
            ExecutionState.REQUESTED: {
                ExecutionState.REQUESTED,
                ExecutionState.STARTED,
                ExecutionState.NOT_EXECUTED,
            },
            ExecutionState.STARTED: {
                ExecutionState.SETTLED,
                ExecutionState.CANCELLED,
                ExecutionState.UNKNOWN,
            },
        }
        if fact.state not in transitions.get(previous.state, set()):
            raise ContextInvariantError("Settled execution facts cannot be changed")
        self._actions[key] = candidate
        if fact.state is not ExecutionState.REQUESTED:
            self.record_fact(
                TraceFactKind(f"action_{fact.state.value}"),
                self.action_ref(*key),
                cycle_id=key[0],
            )

    @property
    def turn_id(self) -> str:
        return self._turn_id

    def entries(self) -> tuple[TraceEntry, ...]:
        """Return every canonical entry, including entries moved into cold nodes."""

        return tuple(self._entries)

    def hot_entries(self) -> tuple[TraceEntry, ...]:
        by_id = {entry.entry_id: entry for entry in self._entries}
        return tuple(by_id[entry_id] for entry_id in self._hot_entry_ids)

    def nodes(self) -> tuple[TraceHeapNode, ...]:
        return tuple(self._nodes.values())

    def head_ref(self) -> str:
        return f"turn:trace@{self._turn_id}"

    def append_decision(
        self,
        message: AssistantMessage,
        *,
        cycle_id: str = "",
        phase: CyclePhase | None = None,
    ) -> TraceEntry:
        return self._append(TraceKind.DECISION, message, cycle_id=cycle_id, phase=phase)

    def append_action_result(
        self,
        message: ToolResultMessage,
        *,
        cycle_id: str = "",
        canonical_message: ToolResultMessage | None = None,
        origin_refs: tuple[str, ...] = (),
    ) -> TraceEntry:
        return self._append(
            TraceKind.ACTION_RESULT,
            canonical_message or message,
            cycle_id=cycle_id,
            phase=CyclePhase.PHASE3,
            visible_overlay=message if canonical_message is not None else None,
            origin_refs=origin_refs,
        )

    def append_phase_note(
        self,
        note: object,
        *,
        cycle_id: str = "",
        phase: CyclePhase | None = None,
        admission_sequence: int | None = None,
    ) -> TraceEntry:
        message = (
            UserMessage.from_text(note, label="phase_note")
            if isinstance(note, str)
            else UserMessage.from_json(note, label="phase_note")
        )
        return self._append(
            TraceKind.PHASE_NOTE,
            message,
            cycle_id=cycle_id,
            phase=phase,
            admission_sequence=admission_sequence,
        )

    def compact(self, *, required_chars: int) -> TraceCompactionReport:
        if required_chars < 0:
            raise ContextContractError("required_chars cannot be negative")
        before_chars = self.visible_char_count()
        folded = self.fold_overlays()
        reclaimed = before_chars - self.visible_char_count()
        compacted: list[TraceEntry] = []
        available = max(0, len(self._hot_entry_ids) - self._min_hot_entries)
        if reclaimed < required_chars and available:
            compacted = self._take_compaction_entries(
                required_chars=max(0, required_chars - reclaimed),
                limit=available,
            )
            self._append_leaf_nodes(compacted)
            self._coalesce_roots()
            reclaimed = before_chars - self.visible_char_count()
        refs = tuple(_node_ref(self._turn_id, node_id) for node_id in self._root_ids)
        return TraceCompactionReport(
            changed=bool(folded or compacted),
            compacted_count=len(compacted),
            folded_overlay_count=folded,
            reclaimed_chars=max(0, reclaimed),
            remaining_hot_count=len(self._hot_entry_ids),
            node_refs=refs,
        )

    def fold_overlays(self) -> int:
        """Remove current-Turn visible overlays from foldable trace entries."""

        folded = 0
        updated: list[TraceEntry] = []
        for entry in self._entries:
            if (
                entry.visible_overlay is None
                or entry.entry_id in self._protected_overlays
            ):
                updated.append(entry)
                continue
            updated.append(replace(entry, visible_overlay=None))
            folded += 1
        if folded:
            self._entries = updated
        return folded

    def inspect(self, ref: str) -> JsonObject:
        if ref == self.head_ref():
            return self._head_payload()
        node = self._node_for_ref(ref)
        if node.kind is TraceHeapNodeKind.LEAF:
            return {"kind": "context_trace_leaf", "ref": ref}
        children = tuple(
            self._nodes[child_id].to_header(turn_id=self._turn_id)
            for child_id in node.child_ids
        )
        return to_json_object(
            {"kind": "context_trace_branch", "ref": ref, "nodes": children}
        )

    def leaf_entries(self, ref: str) -> tuple[TraceEntry, ...]:
        """Return the immutable entries of one inspected leaf."""

        node = self._node_for_ref(ref)
        if node.kind is not TraceHeapNodeKind.LEAF:
            raise ContextInspectRequestError(
                ContextInspectFailureReason.REF_NOT_LEAF,
                "Context inspect requires a leaf ref for interaction content",
                constraint={"ref": ref},
            )
        by_id = {entry.entry_id: entry for entry in self._entries}
        return tuple(by_id[entry_id] for entry_id in node.entry_ids)

    def entries_for_ref(self, ref: str) -> tuple[TraceEntry, ...]:
        if ref == self.head_ref():
            return self.entries()
        prefix = f"{self.head_ref()}#entry/"
        if ref.startswith(prefix):
            entries = tuple(
                item for item in self._entries if item.entry_id == ref[len(prefix) :]
            )
            if entries:
                return entries
            raise ContextInspectRequestError(
                ContextInspectFailureReason.UNKNOWN_REF,
                "Unknown trace entry",
                constraint={"ref": ref},
            )
        node = self._node_for_ref(ref)
        if node.kind is TraceHeapNodeKind.LEAF:
            return self.leaf_entries(ref)
        pending = list(node.child_ids)
        ids: set[str] = set()
        while pending:
            child = self._nodes[pending.pop()]
            ids.update(child.entry_ids)
            pending.extend(child.child_ids)
        return tuple(entry for entry in self._entries if entry.entry_id in ids)

    def render_messages(self) -> tuple[Message, ...]:
        messages: list[Message] = []
        if self._root_ids:
            messages.append(
                UserMessage.from_json(
                    self._head_payload(),
                    label="trace_heap_head",
                )
            )
        messages.extend(entry.visible_message for entry in self.hot_entries())
        return tuple(messages)

    def visible_char_count(self) -> int:
        return sum(_message_chars(message) for message in self.render_messages())

    def seal(self) -> SealedTurnTrace:
        for key, item in tuple(self._actions.items()):
            if item.state is ExecutionState.REQUESTED:
                self._actions[key] = replace(item, state=ExecutionState.NOT_EXECUTED)
                self.record_fact(
                    TraceFactKind.ACTION_NOT_EXECUTED,
                    self.action_ref(*key),
                    cycle_id=key[0],
                )
        return SealedTurnTrace(
            turn_id=self._turn_id,
            entries=self.entries(),
            actions=tuple(self._actions.values()),
            timeline=self.timeline(),
        )

    def _append(
        self,
        kind: TraceKind,
        message: Message,
        *,
        cycle_id: str = "",
        phase: CyclePhase | None = None,
        visible_overlay: Message | None = None,
        origin_refs: tuple[str, ...] = (),
        admission_sequence: int | None = None,
    ) -> TraceEntry:
        entry = TraceEntry(
            entry_id=_entry_id(),
            kind=kind,
            message=message,
            cycle_id=cycle_id,
            phase=phase,
            visible_overlay=visible_overlay,
            origin_refs=origin_refs,
            admission_sequence=admission_sequence,
        )
        self._entries.append(entry)
        self._hot_entry_ids.append(entry.entry_id)
        if visible_overlay is not None:
            self._protected_overlays.add(entry.entry_id)
        return entry

    def _take_compaction_entries(
        self,
        *,
        required_chars: int,
        limit: int,
    ) -> list[TraceEntry]:
        by_id = {entry.entry_id: entry for entry in self._entries}
        selected_ids: list[str] = []
        selected_chars = 0
        target_chars = max(required_chars, self._chunk_max_chars)
        index = 0
        while index < len(self._hot_entry_ids):
            cycle_id = by_id[self._hot_entry_ids[index]].cycle_id
            group: list[str] = []
            group_end = index
            while group_end < len(self._hot_entry_ids):
                entry_id = self._hot_entry_ids[group_end]
                entry = by_id[entry_id]
                if group and entry.cycle_id != cycle_id:
                    break
                group.append(entry_id)
                group_end += 1
                if not cycle_id:
                    break
            if group_end > limit or any(
                item in self._protected_overlays for item in group
            ):
                break
            index = group_end
            selected_ids.extend(group)
            selected_chars += sum(_message_chars(by_id[item].message) for item in group)
            if selected_chars >= target_chars:
                break
        selected = [by_id[entry_id] for entry_id in selected_ids]
        self._hot_entry_ids = self._hot_entry_ids[len(selected_ids) :]
        return selected

    def _append_leaf_nodes(self, entries: list[TraceEntry]) -> None:
        current: list[TraceEntry] = []
        current_chars = 0
        for entry in entries:
            size = _message_chars(entry.message)
            if current and current_chars + size > self._chunk_max_chars:
                self._append_leaf(current)
                current = []
                current_chars = 0
            current.append(entry)
            current_chars += size
        if current:
            self._append_leaf(current)

    def _append_leaf(self, entries: list[TraceEntry]) -> None:
        node = TraceHeapNode(
            node_id=_node_id(),
            kind=TraceHeapNodeKind.LEAF,
            level=0,
            entry_ids=tuple(entry.entry_id for entry in entries),
            cycle_ids=tuple(
                dict.fromkeys(entry.cycle_id for entry in entries if entry.cycle_id)
            ),
            trace_kinds=tuple(sorted({entry.kind.value for entry in entries})),
            action_names=tuple(sorted(_action_names(entries))),
            char_count=sum(_message_chars(entry.message) for entry in entries),
        )
        self._nodes[node.node_id] = node
        self._root_ids.append(node.node_id)

    def _coalesce_roots(self) -> None:
        while len(self._root_ids) >= self._branch_factor:
            child_ids = tuple(self._root_ids[: self._branch_factor])
            children = [self._nodes[child_id] for child_id in child_ids]
            node = TraceHeapNode(
                node_id=_node_id(),
                kind=TraceHeapNodeKind.BRANCH,
                level=max(child.level for child in children) + 1,
                child_ids=child_ids,
                cycle_ids=tuple(
                    dict.fromkeys(
                        cycle_id for child in children for cycle_id in child.cycle_ids
                    )
                ),
                trace_kinds=tuple(
                    sorted({kind for child in children for kind in child.trace_kinds})
                ),
                action_names=tuple(
                    sorted({name for child in children for name in child.action_names})
                ),
                char_count=sum(child.char_count for child in children),
            )
            self._nodes[node.node_id] = node
            self._root_ids = [node.node_id, *self._root_ids[self._branch_factor :]]

    def _head_payload(self) -> JsonObject:
        return to_json_object(
            {
                "kind": "context_trace_head",
                "ref": self.head_ref(),
                "nodes": [
                    self._nodes[node_id].to_header(turn_id=self._turn_id)
                    for node_id in self._root_ids
                ],
            }
        )

    def _node_for_ref(self, ref: str) -> TraceHeapNode:
        prefix = f"turn:trace/{self._turn_id}/"
        if not ref.startswith(prefix):
            raise ContextInspectRequestError(
                ContextInspectFailureReason.INVALID_REF,
                "Trace ref does not belong to the active Turn",
                constraint={"ref": ref},
            )
        node_id = ref[len(prefix) :]
        node = self._nodes.get(node_id)
        if node is None:
            raise ContextInspectRequestError(
                ContextInspectFailureReason.UNKNOWN_REF,
                "Unknown Context trace ref",
                constraint={"ref": ref},
            )
        return node


class PendingInputs:
    """The full list of user inputs for the current turn."""

    def __init__(self) -> None:
        self._inputs: list[PendingInput] = []

    def add(
        self,
        text: str,
        *,
        merged: bool = False,
        input_id: str = "",
        reply_to: str = "",
        received_at: float | None = None,
    ) -> "PendingInput":
        if not text:
            raise ContextContractError("Pending input text must be non-empty")
        item = PendingInput(
            input_id=input_id or f"input_{uuid4().hex}",
            text=text,
            received_at=time() if received_at is None else received_at,
            merged=merged,
            reply_to=reply_to,
        )
        self._inputs.append(item)
        return item

    def unmerged(self) -> tuple["PendingInput", ...]:
        return tuple(item for item in self._inputs if not item.merged)

    def mark_merged(self, input_ids: tuple[str, ...]) -> None:
        ids = set(input_ids)
        unknown = ids - {item.input_id for item in self._inputs}
        if unknown:
            raise ContextContractError(
                f"Unknown pending input id: {sorted(unknown)[0]}"
            )
        self._inputs = [
            replace(item, merged=True) if item.input_id in ids else item
            for item in self._inputs
        ]

    def all(self) -> tuple["PendingInput", ...]:
        return tuple(self._inputs)

    def render_messages(self) -> tuple[Message, ...]:
        return tuple(
            UserMessage.from_text(item.text, label="user_input")
            for item in self._inputs
            if item.merged
        )


@dataclass(frozen=True)
class PendingInput:
    """One user input received for the current turn."""

    input_id: str
    text: str
    received_at: float
    merged: bool = False
    reply_to: str = ""

    def __post_init__(self) -> None:
        if not self.input_id:
            raise ContextInvariantError("PendingInput.input_id must be non-empty")
        if not self.text:
            raise ContextInvariantError("PendingInput.text must be non-empty")


def _entry_id() -> str:
    return f"trace_{uuid4().hex[:8]}"


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


def _node_id() -> str:
    return f"node_{uuid4().hex[:10]}"


def _node_ref(turn_id: str, node_id: str) -> str:
    return f"turn:trace/{turn_id}/{node_id}"


def _action_names(entries: list[TraceEntry]) -> set[str]:
    names: set[str] = set()
    for entry in entries:
        message = entry.message
        if isinstance(message, AssistantMessage):
            names.update(call.name for call in message.tool_calls)
        elif isinstance(message, ToolResultMessage):
            names.add(message.tool_name)
    return names


def _message_chars(message: Message) -> int:
    total = 0
    for part in message.parts:
        if isinstance(part, TextPart):
            total += len(part.text)
        elif isinstance(part, JsonPart):
            total += len(dumps_json(part.value))
    if isinstance(message, AssistantMessage):
        for call in message.tool_calls:
            total += len(call.id) + len(call.name) + len(dumps_json(call.arguments))
        if message.reasoning is not None:
            total += len(message.reasoning.content or "")
            total += len(message.reasoning.summary or "")
            total += sum(
                len(dumps_json(item)) for item in message.reasoning.encrypted_items
            )
    elif isinstance(message, ToolResultMessage):
        total += (
            len(message.call_id) + len(message.tool_name) + len(message.status.value)
        )
    return total
