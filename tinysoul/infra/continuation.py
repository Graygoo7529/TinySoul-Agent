"""Opaque continuation tokens and hard-budget JSON sequence projection."""

from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error as Base64Error
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
import json

from .json import JsonObject, JsonValue, dumps_json, to_json_object, to_json_value


MIN_CONTINUATION_PAGE_CHARS = 1024


class ContinuationFailureReason(StrEnum):
    """Stable failures for one owner-scoped continuation request."""

    INVALID = "invalid_continuation"
    MISMATCH = "continuation_mismatch"
    OUT_OF_RANGE = "continuation_out_of_range"
    CONTENT_CHANGED = "continuation_content_changed"
    BUDGET_TOO_SMALL = "page_budget_too_small"
    INVALID_LIMIT = "invalid_limit"


class ContinuationError(Exception):
    """An opaque continuation cannot be applied to the requested node."""

    def __init__(
        self,
        reason: ContinuationFailureReason,
        message: str,
        *,
        constraint: JsonObject | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.constraint = to_json_object(constraint or {})


@dataclass(frozen=True)
class ContinuationPosition:
    """Internal position within one immutable owner projection."""

    item_index: int = 0
    char_offset: int = 0
    item_digest: str = ""

    def __post_init__(self) -> None:
        for name in ("item_index", "char_offset"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ContinuationError(
                    ContinuationFailureReason.INVALID,
                    "Continuation position must be non-negative",
                )
        if self.char_offset and not _is_digest(self.item_digest):
            raise ContinuationError(
                ContinuationFailureReason.INVALID,
                "Continuation fragment requires a content digest",
            )
        if not self.char_offset and self.item_digest:
            raise ContinuationError(
                ContinuationFailureReason.INVALID,
                "Whole-item continuation cannot carry a content digest",
            )


class OpaqueContinuationCodec:
    """Encode owner-bound positions without exposing their shape to the model."""

    _VERSION = 1

    def __init__(self, *, owner: str, operation: str) -> None:
        if not owner or not operation:
            raise ContinuationError(
                ContinuationFailureReason.INVALID,
                "Continuation owner and operation must be non-empty",
            )
        self._owner = owner
        self._operation = operation

    def encode(
        self,
        position: ContinuationPosition,
        *,
        ref: str,
        binding: JsonObject | None = None,
    ) -> str:
        value = {
            "version": self._VERSION,
            "owner": self._owner,
            "operation": self._operation,
            "ref": ref,
            "binding": to_json_object(binding or {}),
            "position": {
                "item_index": position.item_index,
                "char_offset": position.char_offset,
                "item_digest": position.item_digest,
            },
        }
        body = dumps_json(to_json_object(value)).encode("utf-8")
        encoded = urlsafe_b64encode(body).decode("ascii").rstrip("=")
        digest = sha256(body).hexdigest()
        return f"v{self._VERSION}.{encoded}.{digest}"

    def decode(
        self,
        token: str | None,
        *,
        ref: str,
        binding: JsonObject | None = None,
    ) -> ContinuationPosition:
        if token is None:
            return ContinuationPosition()
        if not isinstance(token, str) or not token:
            raise ContinuationError(
                ContinuationFailureReason.INVALID,
                "Continuation must be a non-empty opaque string",
            )
        try:
            prefix, encoded, digest = token.split(".", 2)
            if prefix != f"v{self._VERSION}":
                raise ValueError("unsupported version")
            padding = "=" * (-len(encoded) % 4)
            body = urlsafe_b64decode(encoded + padding)
            if sha256(body).hexdigest() != digest:
                raise ValueError("digest mismatch")
            raw = json.loads(body.decode("utf-8"))
        except (
            Base64Error,
            ValueError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise ContinuationError(
                ContinuationFailureReason.INVALID,
                "Continuation is invalid; inspect the node again",
            ) from exc
        if not isinstance(raw, dict):
            raise ContinuationError(
                ContinuationFailureReason.INVALID,
                "Continuation is invalid; inspect the node again",
            )
        expected_binding = to_json_object(binding or {})
        expected = {
            "version": self._VERSION,
            "owner": self._owner,
            "operation": self._operation,
            "ref": ref,
            "binding": expected_binding,
        }
        if any(raw.get(name) != value for name, value in expected.items()):
            raise ContinuationError(
                ContinuationFailureReason.MISMATCH,
                "Continuation no longer matches this node; inspect it again",
            )
        position = raw.get("position")
        if not isinstance(position, dict) or set(position) != {
            "item_index",
            "char_offset",
            "item_digest",
        }:
            raise ContinuationError(
                ContinuationFailureReason.INVALID,
                "Continuation is invalid; inspect the node again",
            )
        try:
            return ContinuationPosition(
                item_index=position["item_index"],
                char_offset=position["char_offset"],
                item_digest=position["item_digest"],
            )
        except (KeyError, ContinuationError) as exc:
            raise ContinuationError(
                ContinuationFailureReason.INVALID,
                "Continuation is invalid; inspect the node again",
            ) from exc


def continue_json_sequence(
    values: tuple[JsonValue, ...],
    *,
    base: JsonObject,
    item_field: str,
    continuation: str | None,
    codec: OpaqueContinuationCodec,
    ref: str,
    max_chars: int,
    binding: JsonObject | None = None,
) -> JsonObject:
    """Return one compact page whose canonical JSON fits *max_chars*."""

    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars <= 0:
        raise ContinuationError(
            ContinuationFailureReason.INVALID_LIMIT,
            "Inspect character limit must be positive",
        )
    if not item_field or item_field in base or "next_continuation" in base:
        raise ContinuationError(
            ContinuationFailureReason.INVALID,
            "Inspect page fields are invalid",
        )
    position = codec.decode(continuation, ref=ref, binding=binding)
    items = tuple(to_json_value(value) for value in values)
    if position.item_index >= len(items):
        if continuation is None and not items:
            return _fit_empty(base, item_field=item_field, max_chars=max_chars)
        raise ContinuationError(
            ContinuationFailureReason.OUT_OF_RANGE,
            "Continuation no longer identifies content; inspect the node again",
        )
    if position.char_offset:
        return _continue_fragment(
            items,
            base=base,
            item_field=item_field,
            position=position,
            codec=codec,
            ref=ref,
            binding=binding,
            max_chars=max_chars,
        )

    selected: list[JsonValue] = []
    index = position.item_index
    while index < len(items):
        next_position = (
            ContinuationPosition(item_index=index + 1)
            if index + 1 < len(items)
            else None
        )
        candidate = _page_value(
            base,
            item_field=item_field,
            items=tuple((*selected, items[index])),
            next_continuation=(
                codec.encode(next_position, ref=ref, binding=binding)
                if next_position is not None
                else None
            ),
        )
        if len(dumps_json(candidate)) > max_chars:
            if not selected:
                return _continue_fragment(
                    items,
                    base=base,
                    item_field=item_field,
                    position=position,
                    codec=codec,
                    ref=ref,
                    binding=binding,
                    max_chars=max_chars,
                )
            break
        selected.append(items[index])
        index += 1

    next_position = (
        ContinuationPosition(item_index=index) if index < len(items) else None
    )
    page = _page_value(
        base,
        item_field=item_field,
        items=tuple(selected),
        next_continuation=(
            codec.encode(next_position, ref=ref, binding=binding)
            if next_position is not None
            else None
        ),
    )
    if len(dumps_json(page)) > max_chars:
        raise ContinuationError(
            ContinuationFailureReason.BUDGET_TOO_SMALL,
            "Inspect character limit is too small for page metadata",
        )
    return page


def _continue_fragment(
    items: tuple[JsonValue, ...],
    *,
    base: JsonObject,
    item_field: str,
    position: ContinuationPosition,
    codec: OpaqueContinuationCodec,
    ref: str,
    binding: JsonObject | None,
    max_chars: int,
) -> JsonObject:
    serialized = dumps_json(items[position.item_index])
    digest = f"sha256:{sha256(serialized.encode('utf-8')).hexdigest()}"
    if position.item_digest and position.item_digest != digest:
        raise ContinuationError(
            ContinuationFailureReason.CONTENT_CHANGED,
            "Inspected content changed; inspect the node again",
        )
    if position.char_offset > len(serialized):
        raise ContinuationError(
            ContinuationFailureReason.OUT_OF_RANGE,
            "Continuation no longer identifies content; inspect the node again",
        )
    low = position.char_offset + 1
    high = len(serialized)
    best: JsonObject | None = None
    while low <= high:
        stop = (low + high) // 2
        next_position = (
            ContinuationPosition(
                item_index=position.item_index,
                char_offset=stop,
                item_digest=digest,
            )
            if stop < len(serialized)
            else (
                ContinuationPosition(item_index=position.item_index + 1)
                if position.item_index + 1 < len(items)
                else None
            )
        )
        candidate = _page_value(
            base,
            item_field=item_field,
            items=(),
            fragment=serialized[position.char_offset:stop],
            next_continuation=(
                codec.encode(next_position, ref=ref, binding=binding)
                if next_position is not None
                else None
            ),
        )
        if len(dumps_json(candidate)) <= max_chars:
            best = candidate
            low = stop + 1
        else:
            high = stop - 1
    if best is None:
        raise ContinuationError(
            ContinuationFailureReason.BUDGET_TOO_SMALL,
            "Inspect character limit is too small for one content character",
        )
    return best


def _fit_empty(base: JsonObject, *, item_field: str, max_chars: int) -> JsonObject:
    page = _page_value(base, item_field=item_field, items=())
    if len(dumps_json(page)) > max_chars:
        raise ContinuationError(
            ContinuationFailureReason.BUDGET_TOO_SMALL,
            "Inspect character limit is too small for page metadata",
        )
    return page


def _page_value(
    base: JsonObject,
    *,
    item_field: str,
    items: tuple[JsonValue, ...],
    fragment: str | None = None,
    next_continuation: str | None = None,
) -> JsonObject:
    value: JsonObject = {**to_json_object(base), item_field: list(items)}
    if fragment is not None:
        value["content_fragment"] = {
            "encoding": "canonical_json",
            "text": fragment,
        }
    if next_continuation is not None:
        value["next_continuation"] = next_continuation
    return to_json_object(value)


def _is_digest(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    digest = value.removeprefix("sha256:")
    return len(digest) == 64 and all(char in "0123456789abcdef" for char in digest)
