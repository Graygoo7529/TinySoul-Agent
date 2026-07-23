"""Hard character-budget paging for immutable JSON sequences."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256

from .json import JsonObject, JsonValue, dumps_json, to_json_object, to_json_value


class JsonPageFailureReason(StrEnum):
    """Stable generic reasons for immutable JSON paging failures."""

    INVALID_REQUEST = "invalid_request"
    INVALID_CURSOR = "invalid_cursor"
    CURSOR_OUT_OF_RANGE = "cursor_out_of_range"
    ENTRY_OFFSET_OUT_OF_RANGE = "entry_offset_out_of_range"
    ENTRY_DIGEST_MISMATCH = "entry_digest_mismatch"
    PAGE_BUDGET_TOO_SMALL = "page_budget_too_small"
    INVALID_LIMIT = "invalid_limit"


class JsonPageError(Exception):
    """A paging request cannot be represented within its contract."""

    def __init__(
        self,
        reason: JsonPageFailureReason,
        message: str,
        *,
        constraint: JsonObject | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.constraint = to_json_object(constraint or {})


MIN_JSON_PAGE_CHARS = 1024


@dataclass(frozen=True)
class JsonPageCursor:
    """Stable position in an immutable JSON sequence."""

    entry_index: int = 0
    char_offset: int = 0
    entry_digest: str = ""

    def __post_init__(self) -> None:
        for name in ("entry_index", "char_offset"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise JsonPageError(
                    JsonPageFailureReason.INVALID_CURSOR,
                    f"JSON page cursor {name} must be non-negative",
                    constraint={"field": name},
                )
        if self.char_offset and not _is_digest(self.entry_digest):
            raise JsonPageError(
                JsonPageFailureReason.INVALID_CURSOR,
                "An oversized-entry cursor requires a sha256 entry digest",
                constraint={"field": "entry_digest"},
            )
        if not self.char_offset and self.entry_digest:
            raise JsonPageError(
                JsonPageFailureReason.INVALID_CURSOR,
                "A whole-entry cursor cannot carry an entry digest",
                constraint={"field": "entry_digest"},
            )

    @classmethod
    def from_json(cls, value: object) -> "JsonPageCursor":
        if value is None:
            return cls()
        if not isinstance(value, dict):
            raise JsonPageError(
                JsonPageFailureReason.INVALID_CURSOR,
                "JSON page cursor must be an object",
            )
        if set(value) - {"entry_index", "char_offset", "entry_digest"}:
            raise JsonPageError(
                JsonPageFailureReason.INVALID_CURSOR,
                "JSON page cursor contains unknown fields",
                constraint={
                    "unknown_fields": sorted(
                        set(value) - {"entry_index", "char_offset", "entry_digest"}
                    )
                },
            )
        entry_index = value.get("entry_index", 0)
        char_offset = value.get("char_offset", 0)
        entry_digest = value.get("entry_digest", "")
        if isinstance(entry_index, bool) or not isinstance(entry_index, int):
            raise JsonPageError(
                JsonPageFailureReason.INVALID_CURSOR,
                "JSON page cursor entry_index must be an integer",
                constraint={"field": "entry_index"},
            )
        if isinstance(char_offset, bool) or not isinstance(char_offset, int):
            raise JsonPageError(
                JsonPageFailureReason.INVALID_CURSOR,
                "JSON page cursor char_offset must be an integer",
                constraint={"field": "char_offset"},
            )
        if not isinstance(entry_digest, str):
            raise JsonPageError(
                JsonPageFailureReason.INVALID_CURSOR,
                "JSON page cursor entry_digest must be a string",
                constraint={"field": "entry_digest"},
            )
        return cls(
            entry_index=entry_index,
            char_offset=char_offset,
            entry_digest=entry_digest,
        )

    def to_json(self) -> JsonObject:
        value: JsonObject = {
            "entry_index": self.entry_index,
            "char_offset": self.char_offset,
        }
        if self.entry_digest:
            value["entry_digest"] = self.entry_digest
        return value


def page_json_sequence(
    values: tuple[JsonValue, ...],
    *,
    base: JsonObject,
    item_field: str,
    cursor_unit: str,
    cursor: JsonPageCursor,
    max_chars: int,
    max_entries: int,
    requested_max_chars: int | None = None,
    requested_max_entries: int | None = None,
) -> JsonObject:
    """Build one page whose final canonical JSON never exceeds *max_chars*."""

    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars <= 0:
        raise JsonPageError(
            JsonPageFailureReason.INVALID_LIMIT,
            "JSON page max_chars must be positive",
            constraint={"field": "max_chars"},
        )
    if (
        isinstance(max_entries, bool)
        or not isinstance(max_entries, int)
        or max_entries <= 0
    ):
        raise JsonPageError(
            JsonPageFailureReason.INVALID_LIMIT,
            "JSON page max_entries must be positive",
            constraint={"field": "max_entries"},
        )
    requested_chars = max_chars if requested_max_chars is None else requested_max_chars
    if (
        isinstance(requested_chars, bool)
        or not isinstance(requested_chars, int)
        or requested_chars <= 0
    ):
        raise JsonPageError(
            JsonPageFailureReason.INVALID_LIMIT,
            "JSON page requested_max_chars must be positive",
            constraint={"field": "requested_max_chars"},
        )
    requested_entries = (
        max_entries if requested_max_entries is None else requested_max_entries
    )
    if (
        isinstance(requested_entries, bool)
        or not isinstance(requested_entries, int)
        or requested_entries <= 0
    ):
        raise JsonPageError(
            JsonPageFailureReason.INVALID_LIMIT,
            "JSON page requested_max_entries must be positive",
            constraint={"field": "requested_max_entries"},
        )
    if not item_field or not cursor_unit:
        raise JsonPageError(
            JsonPageFailureReason.INVALID_REQUEST,
            "JSON page field and cursor unit must be non-empty",
        )
    if item_field in base:
        raise JsonPageError(
            JsonPageFailureReason.INVALID_REQUEST,
            "JSON page item field collides with base metadata",
            constraint={"field": item_field},
        )
    items = tuple(to_json_value(value) for value in values)
    if cursor.entry_index > len(items):
        raise JsonPageError(
            JsonPageFailureReason.CURSOR_OUT_OF_RANGE,
            "JSON page cursor exceeds the sequence",
            constraint={"entry_index": cursor.entry_index, "entry_count": len(items)},
        )
    if cursor.char_offset and cursor.entry_index >= len(items):
        raise JsonPageError(
            JsonPageFailureReason.CURSOR_OUT_OF_RANGE,
            "Oversized-entry cursor exceeds the sequence",
            constraint={"entry_index": cursor.entry_index, "entry_count": len(items)},
        )

    empty = _page_value(
        base=base,
        item_field=item_field,
        items=(),
        cursor_unit=cursor_unit,
        entry_count=len(items),
        cursor=cursor,
        next_cursor=None,
        coverage=(cursor.entry_index, cursor.entry_index),
        requested_max_chars=requested_chars,
        effective_max_chars=max_chars,
        requested_max_entries=requested_entries,
        effective_max_entries=max_entries,
    )
    if len(dumps_json(empty)) > max_chars:
        raise JsonPageError(
            JsonPageFailureReason.PAGE_BUDGET_TOO_SMALL,
            "JSON page budget is too small for paging metadata",
            constraint={
                "max_chars": max_chars,
                "required_chars": len(dumps_json(empty)),
            },
        )
    if cursor.entry_index == len(items):
        return empty
    if cursor.char_offset:
        return _oversized_page(
            items,
            base=base,
            item_field=item_field,
            cursor_unit=cursor_unit,
            cursor=cursor,
            max_chars=max_chars,
            max_entries=max_entries,
            requested_max_chars=requested_chars,
            requested_max_entries=requested_entries,
        )

    selected: list[JsonValue] = []
    index = cursor.entry_index
    while index < len(items) and len(selected) < max_entries:
        next_index = index + 1
        next_cursor = (
            JsonPageCursor(entry_index=next_index)
            if next_index < len(items)
            else None
        )
        candidate = _page_value(
            base=base,
            item_field=item_field,
            items=tuple((*selected, items[index])),
            cursor_unit=cursor_unit,
            entry_count=len(items),
            cursor=cursor,
            next_cursor=next_cursor,
            coverage=(cursor.entry_index, next_index),
            requested_max_chars=requested_chars,
            effective_max_chars=max_chars,
            requested_max_entries=requested_entries,
            effective_max_entries=max_entries,
        )
        if len(dumps_json(candidate)) > max_chars:
            if not selected:
                return _oversized_page(
                    items,
                    base=base,
                    item_field=item_field,
                    cursor_unit=cursor_unit,
                    cursor=cursor,
                    max_chars=max_chars,
                    max_entries=max_entries,
                    requested_max_chars=requested_chars,
                    requested_max_entries=requested_entries,
                )
            break
        selected.append(items[index])
        index = next_index

    next_cursor = JsonPageCursor(entry_index=index) if index < len(items) else None
    return _page_value(
        base=base,
        item_field=item_field,
        items=tuple(selected),
        cursor_unit=cursor_unit,
        entry_count=len(items),
        cursor=cursor,
        next_cursor=next_cursor,
        coverage=(cursor.entry_index, index),
        requested_max_chars=requested_chars,
        effective_max_chars=max_chars,
        requested_max_entries=requested_entries,
        effective_max_entries=max_entries,
    )


def _oversized_page(
    items: tuple[JsonValue, ...],
    *,
    base: JsonObject,
    item_field: str,
    cursor_unit: str,
    cursor: JsonPageCursor,
    max_chars: int,
    max_entries: int,
    requested_max_chars: int,
    requested_max_entries: int,
) -> JsonObject:
    serialized = dumps_json(items[cursor.entry_index])
    digest = f"sha256:{sha256(serialized.encode('utf-8')).hexdigest()}"
    if cursor.entry_digest and cursor.entry_digest != digest:
        raise JsonPageError(
            JsonPageFailureReason.ENTRY_DIGEST_MISMATCH,
            "Oversized-entry cursor digest no longer matches",
            constraint={"entry_index": cursor.entry_index},
        )
    if cursor.char_offset > len(serialized):
        raise JsonPageError(
            JsonPageFailureReason.ENTRY_OFFSET_OUT_OF_RANGE,
            "Oversized-entry cursor offset exceeds the entry",
            constraint={
                "entry_index": cursor.entry_index,
                "char_offset": cursor.char_offset,
                "serialized_chars": len(serialized),
            },
        )
    low = cursor.char_offset + 1
    high = len(serialized)
    best: JsonObject | None = None
    while low <= high:
        stop = (low + high) // 2
        next_cursor = (
            JsonPageCursor(
                entry_index=cursor.entry_index,
                char_offset=stop,
                entry_digest=digest,
            )
            if stop < len(serialized)
            else (
                JsonPageCursor(entry_index=cursor.entry_index + 1)
                if cursor.entry_index + 1 < len(items)
                else None
            )
        )
        candidate = _page_value(
            base=base,
            item_field=item_field,
            items=(),
            cursor_unit=cursor_unit,
            entry_count=len(items),
            cursor=cursor,
            next_cursor=next_cursor,
            coverage=(
                cursor.entry_index,
                cursor.entry_index + (1 if stop == len(serialized) else 0),
            ),
            requested_max_chars=requested_max_chars,
            effective_max_chars=max_chars,
            requested_max_entries=requested_max_entries,
            effective_max_entries=max_entries,
            oversized_entry={
                "entry_index": cursor.entry_index,
                "entry_digest": digest,
                "encoding": "canonical_json",
                "char_offset": cursor.char_offset,
                "next_char_offset": stop,
                "serialized_chars": len(serialized),
                "text": serialized[cursor.char_offset:stop],
            },
        )
        if len(dumps_json(candidate)) <= max_chars:
            best = candidate
            low = stop + 1
        else:
            high = stop - 1
    if best is None:
        raise JsonPageError(
            JsonPageFailureReason.PAGE_BUDGET_TOO_SMALL,
            "JSON page budget is too small for one oversized-entry character",
            constraint={"max_chars": max_chars},
        )
    return best


def _page_value(
    *,
    base: JsonObject,
    item_field: str,
    items: tuple[JsonValue, ...],
    cursor_unit: str,
    entry_count: int,
    cursor: JsonPageCursor,
    next_cursor: JsonPageCursor | None,
    coverage: tuple[int, int],
    requested_max_chars: int,
    effective_max_chars: int,
    requested_max_entries: int,
    effective_max_entries: int,
    oversized_entry: JsonObject | None = None,
) -> JsonObject:
    value: JsonObject = {
        **to_json_object(base),
        "cursor_unit": cursor_unit,
        "entry_count": entry_count,
        "returned_entry_count": coverage[1] - coverage[0],
        "returned_entry_indexes": list(range(coverage[0], coverage[1])),
        "entry_coverage": [coverage[0], coverage[1]],
        "remaining_entry_count": entry_count - coverage[1],
        "requested_max_chars": requested_max_chars,
        "effective_max_chars": effective_max_chars,
        "requested_max_entries": requested_max_entries,
        "effective_max_entries": effective_max_entries,
        "cursor": cursor.to_json(),
        "next_cursor": next_cursor.to_json() if next_cursor is not None else None,
        "page_complete": next_cursor is None,
        "truncated": next_cursor is not None,
        item_field: list(items),
    }
    if oversized_entry is not None:
        value["oversized_entry"] = oversized_entry
    return to_json_object(value)


def _is_digest(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    digest = value.removeprefix("sha256:")
    return len(digest) == 64 and all(char in "0123456789abcdef" for char in digest)
