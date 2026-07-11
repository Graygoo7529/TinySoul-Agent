"""Session history facade and bounded background projection."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from tinysoul.context import SessionBackgroundItem, SessionBackgroundSnapshot, TurnSummary
from tinysoul.infra.json import JsonObject, JsonValue, dumps_json, to_json_object

from .config import SessionSettings
from .errors import SessionContractError
from .models import (
    SessionHistoryItem,
    SessionHistoryKind,
    SessionManifest,
    SessionRecord,
)
from .store import SessionStore


class SessionEngine:
    """Persist completed Turns and expose a bounded history head."""

    def __init__(self, settings: SessionSettings) -> None:
        self._settings = settings
        self._store = SessionStore(
            root=settings.root,
            archive_root=settings.archive_root,
        )
        self._manifest = self._store.initialize(date.today().isoformat())

    @property
    def revision(self) -> int:
        return self._manifest.revision

    def background_snapshot(self) -> SessionBackgroundSnapshot:
        self._ensure_today()
        items = self._bounded_background_items()
        return SessionBackgroundSnapshot(
            revision=self._manifest.revision,
            items=tuple(
                SessionBackgroundItem(item_id=item.item_id, content=item.background)
                for item in items
            ),
        )

    def record_turn(
        self,
        *,
        summary: TurnSummary,
        output: JsonObject | None,
        exhausted: bool,
    ) -> None:
        self._ensure_today()
        ref = f"session:turn/{summary.turn_id}"
        if any(item.ref == ref for item in self._manifest.items):
            raise SessionContractError(f"Turn is already recorded in Session: {summary.turn_id}")
        background = _turn_background(
            summary,
            output=output,
            exhausted=exhausted,
            action_names=frozenset(self._settings.background_action_names),
            max_actions=self._settings.background_max_actions_per_turn,
            action_max_chars=self._settings.background_action_max_chars,
        )
        record = SessionRecord(
            ref=ref,
            kind=SessionHistoryKind.TURN,
            content={
                "background": background,
                "completion": summary.to_json(),
                "output": output,
                "exhausted": exhausted,
            },
        )
        self._store.save_record(record)
        item = SessionHistoryItem(
            item_id=summary.turn_id,
            ref=ref,
            kind=SessionHistoryKind.TURN,
            background=background,
            char_count=len(dumps_json(background)),
        )
        items = (*self._manifest.items, item)
        items = self._summarize_once(items)
        manifest = SessionManifest(
            day=self._manifest.day,
            revision=self._manifest.revision + 1,
            items=items,
        )
        self._store.save_manifest(manifest)
        self._manifest = manifest

    def inspect_history(self) -> JsonObject:
        self._ensure_today()
        return {
            "revision": self._manifest.revision,
            "day": self._manifest.day,
            "estimated_chars": sum(item.char_count for item in self._manifest.items),
            "items": [
                {
                    "item_id": item.item_id,
                    "ref": item.ref,
                    "kind": item.kind.value,
                    "char_count": item.char_count,
                    "child_refs": list(item.child_refs),
                }
                for item in self._manifest.items
            ],
        }

    def recall_history(
        self,
        ref: str,
        *,
        max_chars: int | None = None,
        cursor: int = 0,
    ) -> JsonObject:
        self._ensure_today()
        requested = self._settings.recall_max_chars if max_chars is None else max_chars
        if isinstance(requested, bool) or requested <= 0:
            raise SessionContractError("Session recall max_chars must be positive")
        if isinstance(cursor, bool) or cursor < 0:
            raise SessionContractError("Session recall cursor cannot be negative")
        limit = min(requested, self._settings.recall_max_chars)
        record = self._store.load_record(ref)
        return _recall_record(record, max_chars=limit, cursor=cursor)

    def _ensure_today(self) -> None:
        today = date.today().isoformat()
        if self._manifest.day != today:
            self._manifest = self._store.initialize(today)

    def _bounded_background_items(self) -> tuple[SessionHistoryItem, ...]:
        total = sum(item.char_count for item in self._manifest.items)
        if total <= self._settings.background_max_chars:
            return self._manifest.items
        head_background: JsonObject = {
            "kind": "session_overflow_head",
            "inspect_action": "session.history.inspect",
        }
        head_chars = len(dumps_json(head_background)) + 32
        selected: list[SessionHistoryItem] = []
        used = 0
        for item in reversed(self._manifest.items):
            if (
                used + item.char_count + head_chars
                > self._settings.background_max_chars
            ):
                break
            selected.append(item)
            used += item.char_count
        selected.reverse()
        omitted = len(self._manifest.items) - len(selected)
        if omitted <= 0:
            return tuple(selected)
        head_background["omitted_item_count"] = omitted
        head = SessionHistoryItem(
            item_id="session_overflow_head",
            ref="session:summary/session_overflow_head",
            kind=SessionHistoryKind.SUMMARY,
            background=head_background,
            char_count=len(dumps_json(head_background)),
        )
        return (head, *selected)

    def _summarize_once(
        self,
        items: tuple[SessionHistoryItem, ...],
    ) -> tuple[SessionHistoryItem, ...]:
        watermark = int(
            self._settings.background_max_chars
            * self._settings.summary_watermark_ratio
        )
        if sum(item.char_count for item in items) <= watermark:
            return items
        max_split = _summary_split(
            items,
            min_recent_turns=self._settings.min_recent_turns,
        )
        if max_split < 2:
            return items
        summary_id = f"summary_{uuid4().hex[:12]}"
        ref = f"session:summary/{summary_id}"
        target = int(
            self._settings.background_max_chars
            * self._settings.summary_target_ratio
        )
        split = max_split
        for candidate in range(2, max_split + 1):
            candidate_background = _summary_background(ref, items[:candidate])
            candidate_chars = len(dumps_json(candidate_background)) + sum(
                item.char_count for item in items[candidate:]
            )
            if candidate_chars <= target:
                split = candidate
                break
        children = items[:split]
        child_refs = tuple(item.ref for item in children)
        background = _summary_background(ref, children)
        record = SessionRecord(
            ref=ref,
            kind=SessionHistoryKind.SUMMARY,
            content={
                "background": background,
                "child_refs": list(child_refs),
                "children": [item.to_json() for item in children],
            },
        )
        self._store.save_record(record)
        summary_item = SessionHistoryItem(
            item_id=summary_id,
            ref=ref,
            kind=SessionHistoryKind.SUMMARY,
            background=background,
            char_count=len(dumps_json(background)),
            child_refs=child_refs,
        )
        return (summary_item, *items[split:])


def _turn_background(
    summary: TurnSummary,
    *,
    output: JsonObject | None,
    exhausted: bool,
    action_names: frozenset[str],
    max_actions: int,
    action_max_chars: int,
) -> JsonObject:
    asks = tuple(
        text
        for item in summary.inputs
        if isinstance((text := item.get("text")), str) and text
    )
    answer = ""
    references: list[str] = []
    if output is not None:
        raw_answer = output.get("text")
        if isinstance(raw_answer, str):
            answer = raw_answer
        raw_references = output.get("references", [])
        if isinstance(raw_references, list):
            references = [item for item in raw_references if isinstance(item, str)]
    return to_json_object(
        {
            "kind": "session_turn",
            "ref": f"session:turn/{summary.turn_id}",
            "turn_id": summary.turn_id,
            "user_ask": _bounded_asks(asks),
            "actions": _project_action_history(
                summary.trace,
                action_names=action_names,
                max_actions=max_actions,
                action_max_chars=action_max_chars,
            ),
            "answer": _clip(answer, 1800),
            "references": references,
            "exhausted": exhausted,
            "trace_digest": summary.trace_digest,
        }
    )


def _summary_background(
    ref: str,
    children: tuple[SessionHistoryItem, ...],
) -> JsonObject:
    turns: list[JsonObject] = []
    for item in children:
        if item.kind is SessionHistoryKind.SUMMARY:
            turns.append(
                {
                    "kind": "summary",
                    "ref": item.ref,
                    "child_count": len(item.child_refs),
                }
            )
            continue
        turns.append(
            {
                "kind": "turn",
                "ref": item.ref,
                "user_ask": _clip_json_text(item.background.get("user_ask"), 360),
                "answer": _clip_json_text(item.background.get("answer"), 520),
            }
        )
    return to_json_object({
        "kind": "session_summary",
        "ref": ref,
        "child_refs": [item.ref for item in children],
        "turns": turns,
    })


def _summary_split(
    items: tuple[SessionHistoryItem, ...],
    *,
    min_recent_turns: int,
) -> int:
    remaining_turns = min_recent_turns
    split = len(items)
    for index in range(len(items) - 1, -1, -1):
        if items[index].kind is not SessionHistoryKind.TURN:
            continue
        if remaining_turns == 0:
            break
        split = index
        remaining_turns -= 1
    return split


def _recall_record(
    record: SessionRecord,
    *,
    max_chars: int,
    cursor: int,
) -> JsonObject:
    background = record.content.get("background")
    result: JsonObject = {
        "background": to_json_object(background) if isinstance(background, dict) else {},
    }
    if record.kind is SessionHistoryKind.SUMMARY:
        if cursor:
            raise SessionContractError("Session summary recall does not accept a cursor")
        refs = record.content.get("child_refs", [])
        result["child_refs"] = refs if isinstance(refs, list) else []
        return {
            "ref": record.ref,
            "kind": record.kind.value,
            "content": result,
            "cursor": 0,
            "next_cursor": None,
            "truncated": False,
        }
    completion = record.content.get("completion")
    trace_value = completion.get("trace", []) if isinstance(completion, dict) else []
    trace = trace_value if isinstance(trace_value, list) else []
    if cursor > len(trace):
        raise SessionContractError("Session recall cursor exceeds the Turn trace size")
    selected: list[JsonValue] = []
    next_cursor: int | None = None
    for index, entry in enumerate(trace[cursor:], start=cursor):
        candidate = [*selected, entry]
        candidate_record = to_json_object({**result, "trace": candidate})
        if selected and len(dumps_json(candidate_record)) > max_chars:
            next_cursor = index
            break
        selected = candidate
    result["trace"] = selected
    result["trace_entry_count"] = len(trace)
    return {
        "ref": record.ref,
        "kind": record.kind.value,
        "content": result,
        "cursor": cursor,
        "next_cursor": next_cursor,
        "truncated": next_cursor is not None,
    }


def _project_action_history(
    trace: tuple[JsonObject, ...],
    *,
    action_names: frozenset[str],
    max_actions: int,
    action_max_chars: int,
) -> list[JsonObject]:
    calls: dict[str, JsonObject] = {}
    order: list[str] = []
    for entry in trace:
        message = entry.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        tool_calls = message.get("tool_calls", [])
        if not isinstance(tool_calls, list):
            continue
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            call_id = call.get("id")
            name = call.get("name")
            if (
                not isinstance(call_id, str)
                or not isinstance(name, str)
                or name not in action_names
            ):
                continue
            calls[call_id] = to_json_object(
                {
                    "action": name,
                    "call_id": call_id,
                    "arguments": _bounded_json(call.get("arguments"), 600),
                }
            )
            order.append(call_id)
    for entry in trace:
        message = entry.get("message")
        if not isinstance(message, dict) or message.get("role") != "tool_result":
            continue
        call_id = message.get("call_id")
        if not isinstance(call_id, str) or call_id not in calls:
            continue
        calls[call_id]["status"] = message.get("status", "")
        calls[call_id]["result"] = _bounded_json(
            message.get("content"),
            action_max_chars,
        )
    return [calls[call_id] for call_id in order[-max_actions:]]


def _bounded_json(value: object, max_chars: int) -> JsonValue:
    wrapped = to_json_object({"value": value})["value"]
    rendered = dumps_json(wrapped)
    if len(rendered) <= max_chars:
        return wrapped
    preview_limit = max(1, max_chars - 48)
    return {
        "truncated": True,
        "preview": rendered[:preview_limit],
    }


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _bounded_asks(asks: tuple[str, ...]) -> list[str]:
    selected: list[str] = []
    used = 0
    for text in reversed(asks):
        clipped = _clip(text, 1200)
        if selected and used + len(clipped) > 2400:
            break
        selected.append(clipped)
        used += len(clipped)
    selected.reverse()
    return selected


def _clip_json_text(value: object, limit: int) -> str:
    if isinstance(value, str):
        return _clip(value, limit)
    if isinstance(value, list):
        return _clip("\n".join(item for item in value if isinstance(item, str)), limit)
    return ""
