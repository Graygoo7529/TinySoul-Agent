"""Turn trace heap and pending user inputs."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from hashlib import sha256
from time import time
from uuid import uuid4

from tinysoul.infra.json import JsonObject, dumps_json, to_json_object
from tinysoul.llm.messages import (
    AssistantMessage,
    JsonPart,
    Message,
    TextPart,
    ToolResultMessage,
    UserMessage,
)
from tinysoul.runtime import CyclePhase

from .errors import (
    ContextContractError,
    ContextInvariantError,
    ContextTraceFailureReason,
    ContextTraceRequestError,
)


def canonical_trace_digest(trace: tuple[JsonObject, ...]) -> str:
    """Return the content identity of one canonical serialized Turn trace."""

    encoded = dumps_json({"trace": list(trace)}).encode("utf-8")
    return f"sha256:{sha256(encoded).hexdigest()}"


def is_canonical_trace_digest(value: object) -> bool:
    """Return whether *value* is a canonical trace content digest."""

    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    digest = value.removeprefix("sha256:")
    return len(digest) == 64 and all(char in "0123456789abcdef" for char in digest)


class TraceKind(StrEnum):
    """Kinds of canonical turn trace entries."""

    DECISION = "decision"
    ACTION_RESULT = "action_result"
    PHASE_NOTE = "phase_note"


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
            raise ContextInvariantError("TraceHeapNode.kind must be a TraceHeapNodeKind")
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
        return to_json_object(
            {
                "ref": _node_ref(turn_id, self.node_id),
                "kind": self.kind.value,
                "level": self.level,
                "entry_count": len(self.entry_ids),
                "child_count": len(self.child_ids),
                "cycle_ids": list(self.cycle_ids),
                "trace_kinds": list(self.trace_kinds),
                "action_names": list(self.action_names),
                "char_count": self.char_count,
            }
        )


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
class TraceAnchor:
    """One composition-time position in the canonical Turn trace."""

    ref: str
    canonical_revision: int

    def __post_init__(self) -> None:
        if not self.ref:
            raise ContextInvariantError("TraceAnchor.ref must be non-empty")
        if self.canonical_revision < 0:
            raise ContextInvariantError(
                "TraceAnchor.canonical_revision cannot be negative"
            )

    def to_json(self) -> JsonObject:
        return {
            "ref": self.ref,
            "canonical_revision": self.canonical_revision,
        }


@dataclass(frozen=True)
class TraceRecallPage:
    """One stable page from an immutable trace leaf."""

    entries: tuple[TraceEntry, ...]
    cursor: int
    next_cursor: int | None

    @property
    def truncated(self) -> bool:
        return self.next_cursor is not None


@dataclass(frozen=True)
class SealedTurnTrace:
    """Immutable complete trace transferred to Turn completion services."""

    turn_id: str
    entries: tuple[TraceEntry, ...]
    nodes: tuple[TraceHeapNode, ...]
    root_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.turn_id:
            raise ContextInvariantError("SealedTurnTrace.turn_id must be non-empty")


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
            raise ContextContractError(
                "TurnTraceHeap.chunk_max_chars must be positive"
            )
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

    def anchor(self) -> TraceAnchor:
        return TraceAnchor(
            ref=self.head_ref(),
            canonical_revision=len(self._entries),
        )

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
    ) -> TraceEntry:
        message = (
            UserMessage.from_text(note, label="phase_note")
            if isinstance(note, str)
            else UserMessage.from_json(note, label="phase_note")
        )
        return self._append(TraceKind.PHASE_NOTE, message, cycle_id=cycle_id, phase=phase)

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
            if entry.visible_overlay is None:
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
        children = [
            self._nodes[child_id].to_header(turn_id=self._turn_id)
            for child_id in node.child_ids
        ]
        payload = node.to_header(turn_id=self._turn_id)
        return to_json_object({**payload, "children": children})

    def recall(
        self,
        ref: str,
        *,
        max_chars: int,
        cursor: int = 0,
    ) -> TraceRecallPage:
        if isinstance(max_chars, bool) or max_chars <= 0:
            raise ContextContractError("Trace recall max_chars must be positive")
        if isinstance(cursor, bool) or cursor < 0:
            raise ContextContractError("Trace recall cursor cannot be negative")
        node = self._node_for_ref(ref)
        if node.kind is not TraceHeapNodeKind.LEAF:
            raise ContextContractError(
                "Trace recall requires a leaf ref; inspect the branch first"
            )
        if cursor > len(node.entry_ids):
            raise ContextContractError("Trace recall cursor exceeds the leaf size")
        by_id = {entry.entry_id: entry for entry in self._entries}
        selected: list[TraceEntry] = []
        used = 0
        next_cursor: int | None = None
        for index, entry_id in enumerate(node.entry_ids[cursor:], start=cursor):
            entry = by_id[entry_id]
            size = _message_chars(entry.message)
            if selected and used + size > max_chars:
                next_cursor = index
                break
            selected.append(entry)
            used += size
        return TraceRecallPage(
            entries=tuple(selected),
            cursor=cursor,
            next_cursor=next_cursor,
        )

    def recall_entries(self, ref: str) -> tuple[TraceEntry, ...]:
        """Return every immutable entry in one leaf for boundary paging."""

        node = self._node_for_ref(ref)
        if node.kind is not TraceHeapNodeKind.LEAF:
            raise ContextTraceRequestError(
                ContextTraceFailureReason.REF_NOT_LEAF,
                "Trace recall requires a leaf ref; inspect the branch first",
                constraint={"ref": ref},
            )
        by_id = {entry.entry_id: entry for entry in self._entries}
        return tuple(by_id[entry_id] for entry_id in node.entry_ids)

    def render_messages(self) -> tuple[Message, ...]:
        messages: list[Message] = []
        if self._root_ids:
            messages.append(
                UserMessage.from_json(
                    self._head_payload(include_revision=False),
                    label="trace_heap_head",
                )
            )
        messages.extend(entry.visible_message for entry in self.hot_entries())
        return tuple(messages)

    def visible_char_count(self) -> int:
        return sum(_message_chars(message) for message in self.render_messages())

    def seal(self) -> SealedTurnTrace:
        return SealedTurnTrace(
            turn_id=self._turn_id,
            entries=self.entries(),
            nodes=self.nodes(),
            root_ids=tuple(self._root_ids),
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
    ) -> TraceEntry:
        entry = TraceEntry(
            entry_id=_entry_id(),
            kind=kind,
            message=message,
            cycle_id=cycle_id,
            phase=phase,
            visible_overlay=visible_overlay,
            origin_refs=origin_refs,
        )
        self._entries.append(entry)
        self._hot_entry_ids.append(entry.entry_id)
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
            if group_end > limit:
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
            cycle_ids=tuple(dict.fromkeys(entry.cycle_id for entry in entries if entry.cycle_id)),
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

    def _head_payload(self, *, include_revision: bool = True) -> JsonObject:
        value: JsonObject = {
            "ref": self.head_ref(),
            "note": "Earlier TurnTrace entries are available through this heap head.",
            "roots": [
                self._nodes[node_id].to_header(turn_id=self._turn_id)
                for node_id in self._root_ids
            ],
            "hot_entry_count": len(self._hot_entry_ids),
        }
        if include_revision:
            value["canonical_revision"] = len(self._entries)
        return to_json_object(value)

    def _node_for_ref(self, ref: str) -> TraceHeapNode:
        prefix = f"turn:trace/{self._turn_id}/"
        if not ref.startswith(prefix):
            raise ContextTraceRequestError(
                ContextTraceFailureReason.INVALID_REF,
                "Trace ref does not belong to the active Turn",
                constraint={"ref": ref},
            )
        node_id = ref[len(prefix) :]
        node = self._nodes.get(node_id)
        if node is None:
            raise ContextTraceRequestError(
                ContextTraceFailureReason.UNKNOWN_REF,
                "Unknown Context trace ref",
                constraint={"ref": ref},
            )
        return node


class PendingInputs:
    """The full list of user inputs for the current turn."""

    def __init__(self) -> None:
        self._inputs: list[PendingInput] = []

    def add(self, text: str, *, merged: bool = False) -> "PendingInput":
        if not text:
            raise ContextContractError("Pending input text must be non-empty")
        item = PendingInput(
            input_id=f"input_{uuid4().hex[:8]}",
            text=text,
            received_at=time(),
            merged=merged,
        )
        self._inputs.append(item)
        return item

    def unmerged(self) -> tuple["PendingInput", ...]:
        return tuple(item for item in self._inputs if not item.merged)

    def mark_merged(self, input_ids: tuple[str, ...]) -> None:
        ids = set(input_ids)
        unknown = ids - {item.input_id for item in self._inputs}
        if unknown:
            raise ContextContractError(f"Unknown pending input id: {sorted(unknown)[0]}")
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

    def __post_init__(self) -> None:
        if not self.input_id:
            raise ContextInvariantError("PendingInput.input_id must be non-empty")
        if not self.text:
            raise ContextInvariantError("PendingInput.text must be non-empty")


def _entry_id() -> str:
    return f"trace_{uuid4().hex[:8]}"


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
            total += sum(len(dumps_json(item)) for item in message.reasoning.encrypted_items)
    elif isinstance(message, ToolResultMessage):
        total += len(message.call_id) + len(message.tool_name) + len(message.status.value)
    return total
