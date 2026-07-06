"""Turn trace context and pending user inputs."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from time import time
from uuid import uuid4

from tinysoul.llm.messages import (
    AssistantMessage,
    JsonPart,
    Message,
    ToolResultMessage,
    UserMessage,
)
from tinysoul.runtime import CyclePhase

from .errors import ContextContractError, ContextInvariantError


class TraceKind(StrEnum):
    """Kinds of turn trace entries."""

    USER_INPUT = "user_input"
    DECISION = "decision"
    ACTION_RESULT = "action_result"
    PHASE_NOTE = "phase_note"
    SUMMARY_PLACEHOLDER = "summary_placeholder"


@dataclass(frozen=True)
class TraceEntry:
    """One turn trace record holding a model message plus metadata."""

    entry_id: str
    kind: TraceKind
    message: Message
    cycle_id: str = ""
    phase: CyclePhase | None = None

    def __post_init__(self) -> None:
        if not self.entry_id:
            raise ContextInvariantError("TraceEntry.entry_id must be non-empty")
        if not isinstance(self.kind, TraceKind):
            raise ContextInvariantError("TraceEntry.kind must be a TraceKind")
        if self.phase is not None and not isinstance(self.phase, CyclePhase):
            raise ContextInvariantError("TraceEntry.phase must be a CyclePhase")


@dataclass(frozen=True)
class CompressionReport:
    """Result of one trace compression pass."""

    changed: bool
    dropped_count: int
    dropped_kinds: tuple[str, ...]
    remaining_count: int


class TurnTraceContext:
    """Append-only trace of decisions and feedback for the current turn."""

    def __init__(self) -> None:
        self._entries: list[TraceEntry] = []

    def entries(self) -> tuple[TraceEntry, ...]:
        return tuple(self._entries)

    def append_user_input(self, text: str) -> TraceEntry:
        if not text:
            raise ContextContractError("User input text must be non-empty")
        return self._append(
            TraceKind.USER_INPUT,
            UserMessage.from_text(text, label="user_input"),
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
    ) -> TraceEntry:
        return self._append(
            TraceKind.ACTION_RESULT,
            message,
            cycle_id=cycle_id,
            phase=CyclePhase.PHASE3,
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

    def compress_oldest(self, *, keep_recent: int) -> CompressionReport:
        """Drop oldest entries beyond keep_recent, replaced by one summary placeholder."""

        if keep_recent < 0:
            raise ContextContractError("keep_recent cannot be negative")
        placeholders = [
            entry
            for entry in self._entries
            if entry.kind is TraceKind.SUMMARY_PLACEHOLDER
        ]
        droppable = [
            entry
            for entry in self._entries
            if entry.kind is not TraceKind.SUMMARY_PLACEHOLDER
        ]
        drop_count = len(droppable) - keep_recent
        if drop_count <= 0:
            if len(placeholders) > 1:
                count, kinds = _merged_placeholder_stats(placeholders)
                self._entries = [_summary_placeholder(count, kinds), *droppable]
                return CompressionReport(
                    changed=True,
                    dropped_count=0,
                    dropped_kinds=(),
                    remaining_count=len(self._entries),
                )
            return CompressionReport(
                changed=False,
                dropped_count=0,
                dropped_kinds=(),
                remaining_count=len(self._entries),
            )
        dropped = droppable[:drop_count]
        kept = droppable[drop_count:]
        existing_count, existing_kinds = _merged_placeholder_stats(placeholders)
        dropped_kinds = tuple(sorted({entry.kind.value for entry in dropped}))
        merged_kinds = tuple(sorted({*existing_kinds, *dropped_kinds}))
        placeholder = _summary_placeholder(existing_count + len(dropped), merged_kinds)
        self._entries = [placeholder, *kept]
        return CompressionReport(
            changed=True,
            dropped_count=len(dropped),
            dropped_kinds=dropped_kinds,
            remaining_count=len(self._entries),
        )

    def render_messages(self) -> tuple[Message, ...]:
        return tuple(entry.message for entry in self._entries)

    def _append(
        self,
        kind: TraceKind,
        message: Message,
        *,
        cycle_id: str = "",
        phase: CyclePhase | None = None,
    ) -> TraceEntry:
        entry = TraceEntry(
            entry_id=_entry_id(),
            kind=kind,
            message=message,
            cycle_id=cycle_id,
            phase=phase,
        )
        self._entries.append(entry)
        return entry


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


class PendingInputs:
    """The full list of user inputs for the current turn."""

    def __init__(self) -> None:
        self._inputs: list[PendingInput] = []

    def add(self, text: str, *, merged: bool = False) -> PendingInput:
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

    def unmerged(self) -> tuple[PendingInput, ...]:
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

    def all(self) -> tuple[PendingInput, ...]:
        return tuple(self._inputs)


def _entry_id() -> str:
    return f"trace_{uuid4().hex[:8]}"


def _summary_placeholder(dropped_count: int, dropped_kinds: tuple[str, ...]) -> TraceEntry:
    return TraceEntry(
        entry_id=_entry_id(),
        kind=TraceKind.SUMMARY_PLACEHOLDER,
        message=UserMessage.from_json(
            {
                "note": "Earlier turn trace entries were compressed.",
                "dropped_count": dropped_count,
                "dropped_kinds": list(dropped_kinds),
            },
            label="trace_summary",
        ),
    )


def _merged_placeholder_stats(
    placeholders: list[TraceEntry],
) -> tuple[int, tuple[str, ...]]:
    dropped_count = 0
    dropped_kinds: set[str] = set()
    for entry in placeholders:
        for part in entry.message.parts:
            if not isinstance(part, JsonPart):
                continue
            count = part.value.get("dropped_count")
            if isinstance(count, int):
                dropped_count += count
            kinds = part.value.get("dropped_kinds")
            if isinstance(kinds, list):
                for kind in kinds:
                    if isinstance(kind, str):
                        dropped_kinds.add(kind)
    return dropped_count, tuple(sorted(dropped_kinds))
