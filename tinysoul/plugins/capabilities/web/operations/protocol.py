"""Web capability orchestration across worker and Workspace boundaries."""

from __future__ import annotations

import json

from tinysoul.kernel.action import ActionExecutionControl
from tinysoul.infra import JsonObject, JsonValue, dumps_json, to_json_object

from ..errors import WebProcessTimeout, WebWorkerProtocolError

_MAX_WORKER_STDERR = 8_000
_MAX_WARNING_CODES = 20
_WORKER_FAILURE_STRING_FACTS = frozenset(
    {"error_type", "call_type", "content_type", "function_name"}
)
_WORKER_FAILURE_BOOL_FACTS = frozenset(
    {"has_reasoning_content", "has_function", "has_arguments"}
)
_WORKER_FAILURE_TEXT_LIMIT = 128
_WORKER_FAILURE_INT_FACTS = frozenset({"status_code"})
_SAFE_WORKER_ENV = (
    "COMSPEC",
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "WINDIR",
)


def _require_active(control: ActionExecutionControl) -> None:
    if control.is_cancelled():
        raise WebProcessTimeout(
            "Web operation was cancelled before Workspace commit",
            reason=control.cancel_reason or "cancelled",
        )
    if control.is_expired():
        raise WebProcessTimeout(
            "Web operation deadline expired before Workspace commit",
            reason="deadline_expired",
        )


def _worker_failure_facts(response: JsonObject) -> JsonObject:
    facts: JsonObject = {}
    for name in _WORKER_FAILURE_STRING_FACTS:
        value = response.get(name)
        if isinstance(value, str) and 0 < len(value) <= _WORKER_FAILURE_TEXT_LIMIT:
            facts[name] = value
    for name in _WORKER_FAILURE_BOOL_FACTS:
        value = response.get(name)
        if isinstance(value, bool):
            facts[name] = value
    for name in _WORKER_FAILURE_INT_FACTS:
        value = response.get(name)
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and 0 <= value < 1_000
        ):
            facts[name] = value
    call_index = response.get("call_index")
    if (
        isinstance(call_index, int)
        and not isinstance(call_index, bool)
        and 0 <= call_index < 1_000
    ):
        facts["call_index"] = call_index
    return facts


def _worker_response(value: str) -> JsonObject:
    try:
        return to_json_object(json.loads(value))
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise WebWorkerProtocolError("Web worker returned invalid JSON") from exc


def _append_compact_result(
    preview: JsonObject,
    preview_results: list[JsonValue],
    result: JsonObject,
    *,
    limit: int,
) -> None:
    compact: JsonObject = {
        "title": result["title"],
        "url": result["url"],
        "snippet": "",
    }
    preview_results.append(compact)
    base_chars = len(dumps_json(preview))
    if base_chars >= limit:
        preview_results.pop()
        return
    compact["snippet"] = _truncate(str(result["snippet"]), limit - base_chars)
    if len(dumps_json(preview)) > limit:
        compact["snippet"] = ""
    if len(dumps_json(preview)) > limit:
        preview_results.pop()


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."


def _required_string(value: JsonObject, name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item:
        raise WebWorkerProtocolError(f"Web worker field is invalid: {name}")
    return item


def _required_text(
    value: JsonObject,
    name: str,
    *,
    non_empty: bool = False,
) -> str:
    item = value.get(name)
    if not isinstance(item, str) or (non_empty and not item):
        raise WebWorkerProtocolError(f"Web worker field is invalid: {name}")
    return item


def _optional_string(value: JsonObject, name: str) -> str:
    item = value.get(name, "")
    return item if isinstance(item, str) else ""


def _optional_object(value: JsonObject, name: str) -> JsonObject:
    item = value.get(name, {})
    if not isinstance(item, dict):
        raise WebWorkerProtocolError(f"Web worker field is invalid: {name}")
    return to_json_object(item)


def _required_non_negative_int(
    value: JsonObject,
    name: str,
    *,
    positive: bool = False,
) -> int:
    item = value.get(name)
    minimum = 1 if positive else 0
    if isinstance(item, bool) or not isinstance(item, int) or item < minimum:
        raise WebWorkerProtocolError(f"Web worker field is invalid: {name}")
    return item


def _warning_codes(value: JsonObject) -> tuple[str, ...]:
    raw = value.get("warning_codes", [])
    if not isinstance(raw, list) or len(raw) > _MAX_WARNING_CODES:
        raise WebWorkerProtocolError("Web worker warning codes are invalid")
    result: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item:
            raise WebWorkerProtocolError("Web worker warning code is invalid")
        result.append(item)
    return tuple(result)
