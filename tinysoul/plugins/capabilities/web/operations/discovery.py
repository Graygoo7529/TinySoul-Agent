"""Web capability orchestration across worker and Workspace boundaries."""

from __future__ import annotations

from hashlib import sha256
import re
from urllib.parse import urlsplit

from tinysoul.infra import JsonObject, dumps_json, to_json_object

from ..errors import WebContractError, WebWorkerProtocolError


from .protocol import (
    _truncate,
    _required_text,
    _optional_object,
    _required_non_negative_int,
)

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


def _discovery_workspace_link(invoke_id: str, call_id: str) -> str:
    identity = f"{invoke_id}-{call_id}"
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", identity).strip("-")[:80]
    if not normalized:
        normalized = sha256(identity.encode("utf-8")).hexdigest()[:24]
    return f"workspace:web/discovery/{normalized}.json"


def _discovery_payload(value: JsonObject, *, start_url: str) -> JsonObject:
    source = _optional_object(value, "source")
    source_payload: JsonObject = {
        name: _required_text(source, name, non_empty=name in {"url", "final_url"})
        for name in (
            "url",
            "final_url",
            "title",
            "description",
            "h1",
            "canonical_url",
        )
    }
    origin = _url_origin(str(source_payload["url"]))
    if origin is None or _url_origin(start_url) != origin:
        raise WebWorkerProtocolError("Web discovery source URL is invalid")
    if _url_origin(str(source_payload["final_url"])) != origin:
        raise WebWorkerProtocolError("Web discovery final URL left the seed origin")

    raw_pages = value.get("pages")
    if not isinstance(raw_pages, list):
        raise WebWorkerProtocolError("Web discovery pages must be an array")
    pages: list[JsonObject] = []
    state_counts = {"candidate": 0, "visited": 0, "failed": 0}
    for raw in raw_pages:
        if not isinstance(raw, dict):
            raise WebWorkerProtocolError("Web discovery page entry is invalid")
        page = to_json_object(raw)
        state = _required_text(page, "state", non_empty=True)
        if state not in state_counts:
            raise WebWorkerProtocolError("Web discovery page state is invalid")
        page_url = _required_text(page, "url", non_empty=True)
        if _url_origin(page_url) != origin:
            raise WebWorkerProtocolError("Web discovery page left the seed origin")
        normalized: JsonObject = {
            "url": page_url,
            "depth": _required_non_negative_int(page, "depth"),
            "state": state,
            "discovered_from": _required_text(page, "discovered_from"),
            "anchor_text": _required_text(page, "anchor_text"),
            "link_title": _required_text(page, "link_title"),
            "rel": _required_text(page, "rel"),
        }
        discovered_from = str(normalized["discovered_from"])
        if discovered_from and _url_origin(discovered_from) != origin:
            raise WebWorkerProtocolError(
                "Web discovery source reference left the seed origin"
            )
        if state == "visited":
            for name in (
                "final_url",
                "title",
                "description",
                "h1",
                "canonical_url",
            ):
                normalized[name] = _required_text(
                    page,
                    name,
                    non_empty=name == "final_url",
                )
            if _url_origin(str(normalized["final_url"])) != origin:
                raise WebWorkerProtocolError(
                    "Web discovery visited URL left the seed origin"
                )
        elif state == "failed":
            normalized["failure_reason"] = _required_text(
                page,
                "failure_reason",
                non_empty=True,
            )
        state_counts[state] += 1
        pages.append(normalized)

    page_count = _required_non_negative_int(value, "page_count")
    visited_count = _required_non_negative_int(value, "visited_count", positive=True)
    candidate_count = _required_non_negative_int(value, "candidate_count")
    failed_count = _required_non_negative_int(value, "failed_count")
    skipped_count = _required_non_negative_int(value, "skipped_count")
    if page_count != len(pages):
        raise WebWorkerProtocolError("Web discovery page count is invalid")
    if candidate_count != state_counts["candidate"]:
        raise WebWorkerProtocolError("Web discovery candidate count is invalid")
    if failed_count != state_counts["failed"]:
        raise WebWorkerProtocolError("Web discovery failure count is invalid")
    if visited_count != state_counts["visited"] + 1:
        raise WebWorkerProtocolError("Web discovery visited count is invalid")
    stop_reason = _required_text(value, "stop_reason", non_empty=True)
    if stop_reason not in {
        "completed",
        "crawl_time_limit",
        "page_limit",
        "candidate_limit",
        "per_page_link_limit",
    }:
        raise WebWorkerProtocolError("Web discovery stop reason is invalid")
    if value.get("truncated") is not False:
        raise WebWorkerProtocolError("Web discovery canonical result is truncated")
    if value.get("untrusted_external_content") is not True:
        raise WebWorkerProtocolError("Web discovery trust marker is invalid")
    return to_json_object(
        {
            "source": source_payload,
            "pages": pages,
            "page_count": page_count,
            "visited_count": visited_count,
            "candidate_count": candidate_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
            "stop_reason": stop_reason,
            "truncated": False,
            "untrusted_external_content": True,
        }
    )


def _discovery_preview_payload(
    full_payload: JsonObject,
    *,
    target_link: str,
    limit: int,
) -> JsonObject:
    source = full_payload["source"]
    assert isinstance(source, dict)
    compact_source: JsonObject = {
        name: _truncate(str(source.get(name, "")), 240)
        for name in ("url", "final_url", "title", "description", "h1", "canonical_url")
    }
    preview = to_json_object(
        {
            "source": compact_source,
            "pages": [],
            "page_count": full_payload["page_count"],
            "visited_count": full_payload["visited_count"],
            "candidate_count": full_payload["candidate_count"],
            "failed_count": full_payload["failed_count"],
            "skipped_count": full_payload["skipped_count"],
            "stop_reason": full_payload["stop_reason"],
            "truncated": True,
            "see_more_at": target_link,
            "hint": f"See the complete page discovery result at {target_link}",
            "untrusted_external_content": True,
        }
    )
    if len(dumps_json(preview)) > limit:
        for name in compact_source:
            compact_source[name] = _truncate(str(compact_source[name]), 80)
    if len(dumps_json(preview)) > limit:
        raise WebWorkerProtocolError("Web discovery inline result limit is not usable")
    preview_pages = preview["pages"]
    raw_pages = full_payload["pages"]
    assert isinstance(preview_pages, list)
    assert isinstance(raw_pages, list)
    for raw in raw_pages:
        preview_pages.append(raw)
        if len(dumps_json(preview)) > limit:
            preview_pages.pop()
            break
    if len(dumps_json(preview)) > limit:
        raise WebWorkerProtocolError("Web discovery inline preview violates limits")
    return preview


def _url_origin(value: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(value)
        port = parsed.port or 443
    except ValueError:
        return None
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        return None
    return "https", parsed.hostname.rstrip(".").lower(), port


def _validate_discovery_globs(values: tuple[str, ...]) -> None:
    if not isinstance(values, tuple) or len(values) > 20:
        raise WebContractError("Web discovery path globs are invalid")
    for value in values:
        if (
            not isinstance(value, str)
            or not value
            or len(value) > 200
            or any(ord(char) < 32 for char in value)
        ):
            raise WebContractError("Web discovery path glob is invalid")
