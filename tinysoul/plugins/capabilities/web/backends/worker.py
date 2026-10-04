"""Fixed subprocess worker for Web search and page extraction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import asyncio
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from collections.abc import Callable
from typing import cast
from urllib.parse import urlsplit

from lxml import html

from tinysoul.prompts.plugins.capabilities import web as prompt_text
from tinysoul.infra import JsonObject, dumps_json, to_json_object

from ..errors import WebProcessingError
from .network import FetchedPage, fetch_public_page

_KIMI_SEARCH_TOOL_NAME = "$web_search"
_KIMI_SEARCH_CALL_TYPES = frozenset({"builtin_function", "function"})
_KIMI_SHAPE_TEXT_LIMIT = 128


@dataclass(frozen=True)
class _KimiToolRound:
    assistant_message: JsonObject
    tool_messages: tuple[JsonObject, ...]
    search_tokens: int


def main() -> int:
    try:
        request = _request()
        operation = _required_string(request, "operation")
        if operation == "search_by_kimi":
            response = _search_by_kimi(request)
        elif operation == "discover_pages":
            response = _discover_pages(request)
        elif operation in {"fetch_with_defuddle", "fetch_with_trafilatura"}:
            response = _fetch(request, operation=operation)
        else:
            response = _failure(
                "unsupported_operation", prompt_text.WEB_OPERATION_IS_UNSUPPORTED
            )
    except WebProcessingError as exc:
        response = _failure(exc.reason, str(exc), payload=exc.payload)
    except (ImportError, ModuleNotFoundError):
        response = _failure(
            "dependency_unavailable",
            prompt_text.WEB_WORKER_DEPENDENCY_IS_UNAVAILABLE,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        response = _failure(
            "worker_failed", prompt_text.WEB_WORKER_COULD_NOT_COMPLETE_THE_REQUEST
        )
    sys.stdout.write(dumps_json(response))
    return 0 if response.get("ok") is True else 1


def _search_by_kimi(request: JsonObject) -> JsonObject:
    from openai import OpenAI, OpenAIError
    from openai.types.chat import ChatCompletion

    query = _required_string(request, "query")
    base_url = _required_string(request, "base_url")
    model = _required_string(request, "model")
    max_tool_rounds = _required_positive_int(request, "max_tool_rounds")
    max_search_tokens = _required_positive_int(request, "max_search_tokens")
    max_output_tokens = _required_positive_int(request, "max_output_tokens")
    max_result_chars = _required_positive_int(request, "max_result_chars")
    api_key = os.environ.get("TINYSOUL_KIMI_SEARCH_API_KEY", "").strip()
    if not api_key:
        raise WebProcessingError(
            prompt_text.KIMI_SEARCH_CREDENTIAL_IS_UNAVAILABLE,
            reason="credential_unavailable",
        )
    client = OpenAI(api_key=api_key, base_url=base_url)
    messages: list[object] = [
        {
            "role": "system",
            "content": prompt_text.SEARCH_SYSTEM_GUIDE,
        },
        {"role": "user", "content": query},
    ]
    tools = [
        {
            "type": "builtin_function",
            "function": {"name": _KIMI_SEARCH_TOOL_NAME},
        }
    ]
    prompt_tokens = 0
    completion_tokens = 0
    search_tokens = 0
    tool_calls = 0
    create_completion = cast(
        Callable[..., ChatCompletion],
        client.chat.completions.create,
    )
    for _round in range(max_tool_rounds + 1):
        try:
            completion = create_completion(
                model=model,
                messages=messages,
                tools=tools,
                response_format={"type": "json_object"},
                max_tokens=max_output_tokens,
                **_kimi_search_request_options(),
            )
        except OpenAIError as exc:
            raise WebProcessingError(
                prompt_text.KIMI_SEARCH_PROVIDER_REQUEST_FAILED,
                reason="provider_request_failed",
                payload={"error_type": type(exc).__name__},
            ) from exc
        if completion.usage is not None:
            prompt_tokens += completion.usage.prompt_tokens
            completion_tokens += completion.usage.completion_tokens
        if not completion.choices:
            raise WebProcessingError(
                prompt_text.KIMI_SEARCH_RETURNED_NO_COMPLETION_CHOICE,
                reason="provider_protocol_invalid",
            )
        choice = completion.choices[0]
        message = choice.message
        if choice.finish_reason == "tool_calls":
            assistant_message = to_json_object(
                message.model_dump(mode="json", exclude_none=True)
            )
            tool_round = _parse_kimi_tool_round(assistant_message)
            if _round >= max_tool_rounds:
                raise WebProcessingError(
                    prompt_text.search_round_limit(limit=max_tool_rounds),
                    reason="tool_round_limit_exceeded",
                )
            search_tokens += tool_round.search_tokens
            if search_tokens > max_search_tokens:
                raise WebProcessingError(
                    prompt_text.search_token_limit(
                        actual=search_tokens, limit=max_search_tokens
                    ),
                    reason="search_token_limit_exceeded",
                )
            tool_calls += len(tool_round.tool_messages)
            messages.append(tool_round.assistant_message)
            messages.extend(tool_round.tool_messages)
            continue
        if choice.finish_reason != "stop" or not message.content:
            raise WebProcessingError(
                prompt_text.KIMI_SEARCH_DID_NOT_RETURN_A_COMPLETE_RESULT,
                reason="provider_output_incomplete",
            )
        try:
            provider_result = _json_object(message.content)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise WebProcessingError(
                prompt_text.KIMI_SEARCH_RETURNED_INVALID_JSON,
                reason="provider_protocol_invalid",
            ) from exc
        normalized = _normalize_search_result(provider_result)
        normalized["usage"] = to_json_object(
            {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "search_tokens": search_tokens,
                "tool_calls": tool_calls,
            }
        )
        if len(dumps_json(normalized)) > max_result_chars:
            raise WebProcessingError(
                prompt_text.search_result_too_large(limit=max_result_chars),
                reason="result_chars_limit_exceeded",
            )
        return {"ok": True, **normalized}
    raise WebProcessingError(
        prompt_text.KIMI_SEARCH_ENDED_WITHOUT_A_RESULT,
        reason="provider_protocol_invalid",
    )


def _parse_kimi_tool_round(assistant_message: JsonObject) -> _KimiToolRound:
    facts: JsonObject = {
        "has_reasoning_content": "reasoning_content" in assistant_message
    }
    if assistant_message.get("role") != "assistant":
        raise WebProcessingError(
            prompt_text.KIMI_SEARCH_RETURNED_AN_INVALID_ASSISTANT_TOOL_MESSAGE,
            reason="provider_protocol_invalid",
            payload=facts,
        )
    raw_calls = assistant_message.get("tool_calls")
    if not isinstance(raw_calls, list) or not raw_calls:
        raise WebProcessingError(
            prompt_text.KIMI_SEARCH_REQUESTED_AN_EMPTY_TOOL_ROUND,
            reason="provider_protocol_invalid",
            payload=facts,
        )
    tool_messages: list[JsonObject] = []
    search_tokens = 0
    for index, raw_call in enumerate(raw_calls):
        call_facts = _kimi_call_shape_facts(
            assistant_message,
            raw_call,
            call_index=index,
        )
        if not isinstance(raw_call, dict):
            raise WebProcessingError(
                prompt_text.KIMI_SEARCH_RETURNED_AN_UNSUPPORTED_TOOL_CALL_SHAPE,
                reason="provider_protocol_invalid",
                payload=call_facts,
            )
        call_type = raw_call.get("type")
        function = raw_call.get("function")
        if call_type not in _KIMI_SEARCH_CALL_TYPES or not isinstance(
            function,
            dict,
        ):
            raise WebProcessingError(
                prompt_text.KIMI_SEARCH_RETURNED_AN_UNSUPPORTED_TOOL_CALL_SHAPE,
                reason="provider_protocol_invalid",
                payload=call_facts,
            )
        call_id = raw_call.get("id")
        if not isinstance(call_id, str) or not call_id:
            raise WebProcessingError(
                prompt_text.KIMI_SEARCH_RETURNED_AN_INVALID_TOOL_CALL_ID,
                reason="provider_protocol_invalid",
                payload=call_facts,
            )
        if function.get("name") != _KIMI_SEARCH_TOOL_NAME:
            raise WebProcessingError(
                prompt_text.KIMI_SEARCH_REQUESTED_AN_UNSUPPORTED_TOOL,
                reason="provider_protocol_invalid",
                payload=call_facts,
            )
        raw_arguments = function.get("arguments")
        if not isinstance(raw_arguments, str) or not raw_arguments:
            raise WebProcessingError(
                prompt_text.KIMI_SEARCH_RETURNED_INVALID_TOOL_ARGUMENTS,
                reason="provider_protocol_invalid",
                payload=call_facts,
            )
        try:
            arguments = _json_object(raw_arguments)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise WebProcessingError(
                prompt_text.KIMI_SEARCH_RETURNED_INVALID_TOOL_ARGUMENTS,
                reason="provider_protocol_invalid",
                payload=call_facts,
            ) from exc
        search_tokens += _search_token_usage(arguments)
        tool_messages.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "name": _KIMI_SEARCH_TOOL_NAME,
                "content": raw_arguments,
            }
        )
    return _KimiToolRound(
        assistant_message=assistant_message,
        tool_messages=tuple(tool_messages),
        search_tokens=search_tokens,
    )


def _kimi_search_request_options() -> dict[str, object]:
    return {"extra_body": {"thinking": {"type": "disabled"}}}


def _kimi_call_shape_facts(
    assistant_message: JsonObject,
    raw_call: object,
    *,
    call_index: int,
) -> JsonObject:
    facts: JsonObject = {
        "call_index": call_index,
        "has_reasoning_content": "reasoning_content" in assistant_message,
        "has_function": False,
        "has_arguments": False,
    }
    if not isinstance(raw_call, dict):
        return facts
    call_type = raw_call.get("type")
    if isinstance(call_type, str):
        facts["call_type"] = call_type[:_KIMI_SHAPE_TEXT_LIMIT]
    function = raw_call.get("function")
    if not isinstance(function, dict):
        return facts
    facts["has_function"] = True
    function_name = function.get("name")
    if isinstance(function_name, str):
        facts["function_name"] = function_name[:_KIMI_SHAPE_TEXT_LIMIT]
    facts["has_arguments"] = isinstance(function.get("arguments"), str)
    return facts


def _discover_pages(request: JsonObject) -> JsonObject:
    from .discovery import DiscoveryRequest, discover_pages

    max_result_chars = _required_positive_int(request, "max_result_chars")
    result = asyncio.run(
        discover_pages(
            DiscoveryRequest(
                start_url=_required_string(request, "start_url"),
                max_visit_depth=_required_non_negative_int(
                    request,
                    "max_visit_depth",
                ),
                include_globs=_required_string_tuple(request, "include_globs"),
                exclude_globs=_required_string_tuple(request, "exclude_globs"),
                max_pages=_required_positive_int(request, "max_pages"),
                max_candidates=_required_positive_int(request, "max_candidates"),
                max_links_per_page=_required_positive_int(
                    request,
                    "max_links_per_page",
                ),
                max_concurrency=_required_positive_int(
                    request,
                    "max_concurrency",
                ),
                max_tasks_per_minute=_required_positive_int(
                    request,
                    "max_tasks_per_minute",
                ),
                max_request_retries=_required_non_negative_int(
                    request,
                    "max_request_retries",
                ),
                max_crawl_seconds=_required_positive_int(
                    request,
                    "max_crawl_seconds",
                ),
                max_source_bytes=_required_positive_int(
                    request,
                    "max_source_bytes",
                ),
                request_timeout_seconds=_required_positive_int(
                    request,
                    "request_timeout_seconds",
                ),
                max_redirects=_required_positive_int(request, "max_redirects"),
                user_agent=_required_string(request, "user_agent"),
                allow_query_links=_required_bool(request, "allow_query_links"),
            )
        )
    )
    if len(dumps_json(result)) > max_result_chars:
        raise WebProcessingError(
            prompt_text.discovery_result_too_large(limit=max_result_chars),
            reason="result_chars_limit_exceeded",
        )
    return {"ok": True, **result}


def _fetch(request: JsonObject, *, operation: str) -> JsonObject:
    output_path = Path(_required_string(request, "output_path"))
    output_path.mkdir(parents=True, exist_ok=True)
    page = fetch_public_page(
        _required_string(request, "url"),
        max_bytes=_required_positive_int(request, "max_source_bytes"),
        timeout_seconds=_required_positive_int(request, "request_timeout_seconds"),
        max_redirects=_required_positive_int(request, "max_redirects"),
        user_agent=_required_string(request, "user_agent"),
    )
    max_output_chars = _required_positive_int(request, "max_output_chars")
    if operation == "fetch_with_defuddle":
        title, body = _extract_with_defuddle(
            page,
            output_path=output_path,
            executable=_required_string(request, "defuddle_executable"),
            max_output_chars=max_output_chars,
        )
        extractor = "defuddle"
    else:
        title, body = _extract_with_trafilatura(page)
        extractor = "trafilatura"
    if not body.strip():
        raise WebProcessingError(
            prompt_text.WEB_EXTRACTOR_DID_NOT_PRODUCE_READABLE_CONTENT,
            reason="no_usable_output",
        )
    markdown = _document_markdown(
        title=title,
        source_url=page.final_url,
        extractor=extractor,
        body=body,
    )
    if len(markdown) > max_output_chars:
        raise WebProcessingError(
            prompt_text.markdown_too_large(
                actual=len(markdown), limit=max_output_chars
            ),
            reason="output_chars_limit_exceeded",
        )
    document = output_path / "document.md"
    document.write_text(markdown, encoding="utf-8")
    excerpt = _excerpt(body, _required_positive_int(request, "max_excerpt_chars"))
    return {
        "ok": True,
        "markdown_file": document.name,
        "extractor": extractor,
        "title": title,
        "excerpt": excerpt,
        "content_chars": len(markdown),
        "remote_image_count": _remote_image_count(markdown),
        "warning_codes": [],
    }


def _extract_with_trafilatura(page: FetchedPage) -> tuple[str, str]:
    import trafilatura

    try:
        body = trafilatura.extract(
            page.html,
            url=page.final_url,
            output_format="markdown",
            include_links=True,
            include_images=True,
            include_tables=True,
        )
    # Third-party extractor exception types are not a stable public contract.
    except Exception as exc:
        raise WebProcessingError(
            prompt_text.TRAFILATURA_COULD_NOT_EXTRACT_THE_FETCHED_PAGE,
            reason="extractor_failed",
            payload={"error_type": type(exc).__name__},
        ) from exc
    return _html_title(page.html, page.final_url), body or ""


def _extract_with_defuddle(
    page: FetchedPage,
    *,
    output_path: Path,
    executable: str,
    max_output_chars: int,
) -> tuple[str, str]:
    source = output_path / "source.html"
    result = output_path / "defuddle.json"
    source.write_text(page.html, encoding="utf-8")
    argv = [
        executable,
        "parse",
        str(source),
        "--markdown",
        "--json",
        "--output",
        str(result),
    ]
    if os.name == "nt" and Path(executable).suffix.lower() in {".cmd", ".bat"}:
        command = subprocess.list2cmdline(argv)
        argv = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", command]
    completed = subprocess.run(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        shell=False,
    )
    if completed.returncode != 0 or not result.is_file():
        raise WebProcessingError(
            prompt_text.DEFUDDLE_COULD_NOT_EXTRACT_THE_FETCHED_PAGE,
            reason="extractor_failed",
        )
    value = _read_bounded_json_file(
        result,
        max_bytes=max_output_chars * 8 + 64 * 1024,
    )
    content = value.get("contentMarkdown", value.get("content", ""))
    if not isinstance(content, str):
        raise WebProcessingError(
            prompt_text.DEFUDDLE_RETURNED_AN_INVALID_RESULT,
            reason="extractor_protocol_invalid",
        )
    title = value.get("title", "")
    if not isinstance(title, str) or not title.strip():
        title = _html_title(page.html, page.final_url)
    return title.strip(), content


def _normalize_search_result(
    value: JsonObject,
) -> JsonObject:
    answer = _required_string(value, "answer").strip()
    raw_results = value.get("results")
    if not isinstance(raw_results, list):
        raise WebProcessingError(
            prompt_text.KIMI_SEARCH_RESULTS_MUST_BE_AN_ARRAY,
            reason="provider_protocol_invalid",
        )
    results: list[JsonObject] = []
    for item in raw_results:
        if not isinstance(item, dict):
            raise WebProcessingError(
                prompt_text.KIMI_SEARCH_RESULT_ENTRY_IS_INVALID,
                reason="provider_protocol_invalid",
            )
        result = to_json_object(item)
        title = _required_string(result, "title").strip()
        url = _required_string(result, "url").strip()
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise WebProcessingError(
                prompt_text.KIMI_SEARCH_RETURNED_AN_INVALID_SOURCE_URL,
                reason="provider_protocol_invalid",
            )
        snippet = _required_string(result, "snippet").strip()
        results.append({"title": title, "url": url, "snippet": snippet})
    return to_json_object({"answer": answer, "results": results})


def _read_bounded_json_file(path: Path, *, max_bytes: int) -> JsonObject:
    try:
        with path.open("rb") as handle:
            data = handle.read(max_bytes + 1)
    except OSError as exc:
        raise WebProcessingError(
            prompt_text.DEFUDDLE_RESULT_COULD_NOT_BE_READ,
            reason="extractor_protocol_invalid",
        ) from exc
    if len(data) > max_bytes:
        raise WebProcessingError(
            prompt_text.staged_result_too_large(limit=max_bytes),
            reason="staged_result_bytes_limit_exceeded",
        )
    try:
        return _json_object(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise WebProcessingError(
            prompt_text.DEFUDDLE_RETURNED_AN_INVALID_RESULT,
            reason="extractor_protocol_invalid",
        ) from exc


def _document_markdown(
    *,
    title: str,
    source_url: str,
    extractor: str,
    body: str,
) -> str:
    safe_title = " ".join(title.split()) or "Fetched Web Page"
    retrieved = datetime.now(UTC).isoformat()
    return (
        f"# {safe_title}\n\n"
        f"> Source: {source_url}\n"
        f"> Retrieved: {retrieved}\n"
        f"> Extractor: {extractor}\n\n"
        f"{body.strip()}\n"
    )


def _html_title(value: str, url: str) -> str:
    try:
        document = html.fromstring(value)
        titles = document.xpath("//title/text()")
    except Exception:
        titles = []
    if titles:
        normalized = " ".join(str(titles[0]).split())
        if normalized:
            return normalized
    return urlsplit(url).hostname or "Fetched Web Page"


def _remote_image_count(markdown: str) -> int:
    markdown_images = re.findall(r"!\[[^\]]*\]\((https?://[^)\s]+)", markdown)
    html_images = re.findall(
        r"<img\b[^>]*\bsrc=[\"'](https?://[^\"']+)",
        markdown,
        flags=re.IGNORECASE,
    )
    return len(set((*markdown_images, *html_images)))


def _excerpt(value: str, limit: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "..."


def _request() -> JsonObject:
    return _json_object(sys.stdin.read())


def _json_object(value: str) -> JsonObject:
    parsed = json.loads(value)
    return to_json_object(parsed)


def _required_string(value: JsonObject, name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item:
        raise WebProcessingError(
            prompt_text.WEB_WORKER_REQUEST_OR_RESPONSE_IS_INVALID,
            reason="worker_protocol_invalid",
        )
    return item


def _required_positive_int(value: JsonObject, name: str) -> int:
    item = value.get(name)
    if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
        raise WebProcessingError(
            prompt_text.WEB_WORKER_NUMERIC_BOUNDARY_IS_INVALID,
            reason="worker_protocol_invalid",
        )
    return item


def _required_non_negative_int(value: JsonObject, name: str) -> int:
    item = value.get(name)
    if isinstance(item, bool) or not isinstance(item, int) or item < 0:
        raise WebProcessingError(
            prompt_text.WEB_WORKER_NUMERIC_BOUNDARY_IS_INVALID,
            reason="worker_protocol_invalid",
        )
    return item


def _required_bool(value: JsonObject, name: str) -> bool:
    item = value.get(name)
    if not isinstance(item, bool):
        raise WebProcessingError(
            prompt_text.WEB_WORKER_BOOLEAN_BOUNDARY_IS_INVALID,
            reason="worker_protocol_invalid",
        )
    return item


def _required_string_tuple(value: JsonObject, name: str) -> tuple[str, ...]:
    item = value.get(name)
    if not isinstance(item, list) or any(
        not isinstance(entry, str) or not entry for entry in item
    ):
        raise WebProcessingError(
            prompt_text.WEB_WORKER_STRING_LIST_IS_INVALID,
            reason="worker_protocol_invalid",
        )
    return tuple(cast(list[str], item))


def _search_token_usage(arguments: JsonObject) -> int:
    usage = arguments.get("usage")
    if not isinstance(usage, dict):
        return 0
    value = usage.get("total_tokens", 0)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _failure(
    reason: str,
    message: str,
    *,
    payload: JsonObject | None = None,
) -> JsonObject:
    return {"ok": False, "reason": reason, "message": message, **(payload or {})}


if __name__ == "__main__":
    raise SystemExit(main())
