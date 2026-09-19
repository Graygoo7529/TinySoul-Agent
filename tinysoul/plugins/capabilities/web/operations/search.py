"""Web capability orchestration across worker and Workspace boundaries."""

from __future__ import annotations

from hashlib import sha256
import re
from urllib.parse import urlsplit

from tinysoul.infra import JsonObject, dumps_json, to_json_object

from ..errors import WebWorkerProtocolError


from .protocol import _append_compact_result, _truncate, _required_string


def _search_results(
    value: JsonObject,
) -> list[JsonObject]:
    raw = value.get("results")
    if not isinstance(raw, list):
        raise WebWorkerProtocolError("Web search results must be an array")
    results: list[JsonObject] = []
    for item in raw:
        if not isinstance(item, dict):
            raise WebWorkerProtocolError("Web search result entry is invalid")
        result = to_json_object(item)
        url = _required_string(result, "url")
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise WebWorkerProtocolError("Web search source URL is invalid")
        snippet = _required_string(result, "snippet")
        results.append(
            {"title": _required_string(result, "title"), "url": url, "snippet": snippet}
        )
    return results


def _search_workspace_link(invoke_id: str, call_id: str) -> str:
    identity = f"{invoke_id}-{call_id}"
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", identity).strip("-")[:80]
    if not normalized:
        normalized = sha256(identity.encode("utf-8")).hexdigest()[:24]
    return f"workspace:web/search/{normalized}.md"


def _search_markdown(
    *,
    query: str,
    answer: str,
    results: list[JsonObject],
) -> str:
    lines = [
        "# Web Search Result",
        "",
        "## Query",
        "",
        query,
        "",
        "## Answer",
        "",
        answer,
    ]
    lines.extend(("", "## Results", ""))
    for index, result in enumerate(results, start=1):
        title = str(result["title"]).replace("]", "\\]").replace("\n", " ")
        lines.extend(
            (
                f"{index}. [{title}]({result['url']})",
                f"   {result['snippet']}",
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def _search_preview_payload(
    *,
    answer: str,
    results: list[JsonObject],
    usage: JsonObject,
    target_link: str,
    limit: int,
) -> JsonObject:
    preview: JsonObject = {
        "answer": "",
        "results": [],
        "result_count": len(results),
        "truncated": True,
        "see_more_at": target_link,
        "hint": f"See the complete answer and results at {target_link}",
        "untrusted_external_content": True,
        "usage": usage,
    }
    preview_results = preview["results"]
    assert isinstance(preview_results, list)
    fixed_chars = len(dumps_json(preview))
    if fixed_chars + 40 > limit:
        raise WebWorkerProtocolError("Kimi inline result limit is not usable")
    answer_budget = min(len(answer), max(40, (limit - fixed_chars) // 2))
    preview["answer"] = _truncate(answer, answer_budget)
    for result in results:
        preview_results.append(result)
        if len(dumps_json(preview)) > limit:
            preview_results.pop()
            _append_compact_result(preview, preview_results, result, limit=limit)
            break
    if len(dumps_json(preview)) > limit:
        raise WebWorkerProtocolError("Kimi inline result preview violates limits")
    return preview
