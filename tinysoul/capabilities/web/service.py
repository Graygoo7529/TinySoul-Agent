"""Web capability orchestration across worker and Workspace boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import sys
from urllib.parse import urlsplit

from tinysoul.action import ActionExecutionControl
from tinysoul.action.backends import (
    ControlledProcessRunner,
    ProcessRequest,
    ProcessStatus,
)
from tinysoul.infra import (
    JsonObject,
    JsonValue,
    StagingDirectoryManager,
    dumps_json,
    to_json_object,
)
from tinysoul.workspace import (
    WorkspaceBundleWrite,
    WorkspaceEngine,
    WorkspaceLink,
    WorkspaceRetention,
)

from .config import WebSettings
from .errors import (
    WebContractError,
    WebProcessingError,
    WebProcessTimeout,
    WebWorkerProtocolError,
)
from .models import (
    WebDiscoveryResult,
    WebExtractor,
    WebFetchResult,
    WebSearchResult,
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


class WebCapabilityService:
    """Run Web operations in a fixed worker and commit bounded artifacts."""

    def __init__(
        self,
        *,
        workspace: WorkspaceEngine,
        settings: WebSettings,
        runtime_env: Mapping[str, str],
        staging: StagingDirectoryManager,
        kimi_api_key: str = "",
        process_runner: ControlledProcessRunner | None = None,
    ) -> None:
        self._workspace = workspace
        self._settings = settings
        self._runtime_env = dict(runtime_env)
        self._staging = staging
        self._kimi_api_key = kimi_api_key
        self._process_runner = process_runner or ControlledProcessRunner()
        self._defuddle_executable = (
            shutil.which("defuddle", path=self._runtime_env.get("PATH"))
            or "defuddle"
        )

    def search_by_kimi(
        self,
        *,
        query: str,
        invoke_id: str,
        call_id: str,
        owner_turn_id: str,
        control: ActionExecutionControl,
    ) -> WebSearchResult:
        """Return answer and sources inline, spilling only oversized output."""

        search = self._settings.search_by_kimi
        if not isinstance(query, str) or not query.strip():
            raise WebContractError("Kimi search query must be non-empty")
        if len(query) > search.max_query_chars:
            raise WebProcessingError(
                "Kimi search query exceeds the configured limit",
                reason="query_chars_limit_exceeded",
            )
        if not isinstance(invoke_id, str) or not invoke_id:
            raise WebContractError("Kimi search invoke id must be non-empty")
        if not isinstance(call_id, str) or not call_id:
            raise WebContractError("Kimi search call id must be non-empty")
        if not isinstance(owner_turn_id, str):
            raise WebContractError("Kimi search owner turn id must be a string")
        if not self._kimi_api_key:
            raise WebProcessingError(
                "Kimi Search credential is unavailable",
                reason="credential_unavailable",
            )
        _require_active(control)
        response = self._run_worker(
            {
                "operation": "search_by_kimi",
                "query": query.strip(),
                "base_url": search.base_url,
                "model": search.model,
                "max_tool_rounds": search.max_tool_rounds,
                "max_search_tokens": search.max_search_tokens,
                "max_output_tokens": search.max_output_tokens,
                "max_result_chars": search.max_result_chars,
            },
            control=control,
            stdout_limit=search.max_result_chars + 16_000,
            include_kimi_key=True,
        )
        answer = _required_string(response, "answer")
        results = _search_results(response)
        usage = _optional_object(response, "usage")
        canonical_payload = to_json_object(
            {"answer": answer, "results": results, "usage": usage}
        )
        if len(dumps_json(canonical_payload)) > search.max_result_chars:
            raise WebWorkerProtocolError("Kimi search result violates result limits")
        full_payload = to_json_object(
            {
                "answer": answer,
                "results": results,
                "result_count": len(results),
                "truncated": False,
                "untrusted_external_content": True,
                "usage": usage,
            }
        )
        if len(dumps_json(full_payload)) <= search.max_inline_chars:
            return WebSearchResult(payload=full_payload)

        target_link = _search_workspace_link(invoke_id, call_id)
        markdown = _search_markdown(query=query.strip(), answer=answer, results=results)
        _require_active(control)
        committed = self._workspace.write_bundle(
            (
                WorkspaceBundleWrite(
                    link=target_link,
                    data=markdown.encode("utf-8"),
                    retention=WorkspaceRetention.DAY,
                    owner_turn_id=owner_turn_id,
                ),
            )
        )
        payload = _search_preview_payload(
            answer=answer,
            results=results,
            usage=usage,
            target_link=target_link,
            limit=search.max_inline_chars,
        )
        return WebSearchResult(
            payload=payload,
            manifest=committed.manifest,
            record=committed.records[0],
        )

    def fetch(
        self,
        *,
        extractor: WebExtractor,
        url: str,
        target_link: str,
        overwrite: bool,
        expected_target_digest: str,
        owner_turn_id: str,
        control: ActionExecutionControl,
    ) -> WebFetchResult:
        """Fetch and extract one public page into Workspace Markdown."""

        if not isinstance(extractor, WebExtractor):
            raise WebContractError("Web extractor is invalid")
        if not isinstance(url, str) or not url:
            raise WebContractError("Web fetch URL must be non-empty")
        target = WorkspaceLink.parse(target_link)
        if target.path.suffix.lower() != ".md":
            raise WebContractError("Web fetch target must end with .md")
        if not isinstance(overwrite, bool):
            raise WebContractError("Web fetch overwrite must be boolean")
        if not isinstance(expected_target_digest, str):
            raise WebContractError("Web fetch target digest guard must be a string")
        if expected_target_digest and not overwrite:
            raise WebContractError(
                "Web fetch expected target digest requires overwrite=true"
            )
        if not isinstance(owner_turn_id, str):
            raise WebContractError("Web fetch owner turn id must be a string")
        _require_active(control)
        with self._staging.allocate("web") as output_path:
            operation = f"fetch_with_{extractor.value}"
            worker_request: JsonObject = {
                "operation": operation,
                "url": url,
                "output_path": str(output_path),
                "max_source_bytes": self._settings.max_source_bytes,
                "max_output_chars": self._settings.max_output_chars,
                "max_excerpt_chars": self._settings.max_excerpt_chars,
                "request_timeout_seconds": self._settings.request_timeout_seconds,
                "max_redirects": self._settings.max_redirects,
                "user_agent": self._settings.user_agent,
            }
            if extractor is WebExtractor.DEFUDDLE:
                worker_request["defuddle_executable"] = self._defuddle_executable
            response = self._run_worker(
                worker_request,
                control=control,
                stdout_limit=32_000,
            )
            markdown_file = _required_string(response, "markdown_file")
            if Path(markdown_file).name != markdown_file:
                raise WebWorkerProtocolError("Web worker Markdown path is invalid")
            markdown_path = output_path / markdown_file
            try:
                data = markdown_path.read_bytes()
                text = data.decode("utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise WebWorkerProtocolError(
                    "Web worker Markdown output is unreadable"
                ) from exc
            if not text.strip() or len(text) > self._settings.max_output_chars:
                raise WebWorkerProtocolError(
                    "Web worker Markdown output violates limits"
                )
            _require_active(control)
            committed = self._workspace.write_bundle(
                (
                    WorkspaceBundleWrite(
                        link=str(target),
                        data=data,
                        overwrite=overwrite,
                        expected_digest=expected_target_digest,
                        retention=WorkspaceRetention.DAY,
                        owner_turn_id=owner_turn_id,
                    ),
                )
            )
        response_extractor = _required_string(response, "extractor")
        if response_extractor != extractor.value:
            raise WebWorkerProtocolError("Web worker extractor identity is invalid")
        return WebFetchResult(
            markdown_link=str(target),
            extractor=extractor,
            title=_required_string(response, "title"),
            excerpt=_required_string(response, "excerpt"),
            content_chars=_required_non_negative_int(
                response,
                "content_chars",
                positive=True,
            ),
            remote_image_count=_required_non_negative_int(
                response,
                "remote_image_count",
            ),
            manifest=committed.manifest,
            record=committed.records[0],
            warning_codes=_warning_codes(response),
        )

    def discover_pages(
        self,
        *,
        start_url: str,
        max_visit_depth: int,
        include_globs: tuple[str, ...],
        exclude_globs: tuple[str, ...],
        invoke_id: str,
        call_id: str,
        owner_turn_id: str,
        control: ActionExecutionControl,
    ) -> WebDiscoveryResult:
        """Discover bounded same-origin page candidates without saving bodies."""

        discovery = self._settings.discover_pages
        if not isinstance(start_url, str) or not start_url.strip():
            raise WebContractError("Web discovery seed URL must be non-empty")
        if len(start_url) > 4_000:
            raise WebProcessingError(
                "Web discovery seed URL exceeds the configured protocol limit",
                reason="url_chars_limit_exceeded",
            )
        if (
            isinstance(max_visit_depth, bool)
            or not isinstance(max_visit_depth, int)
            or max_visit_depth < 0
            or max_visit_depth > discovery.max_visit_depth
        ):
            raise WebProcessingError(
                "Web discovery visit depth exceeds the configured limit",
                reason="visit_depth_limit_exceeded",
            )
        _validate_discovery_globs(include_globs)
        _validate_discovery_globs(exclude_globs)
        for value, name in (
            (invoke_id, "invoke id"),
            (call_id, "call id"),
        ):
            if not isinstance(value, str) or not value:
                raise WebContractError(f"Web discovery {name} must be non-empty")
        if not isinstance(owner_turn_id, str):
            raise WebContractError("Web discovery owner turn id must be a string")
        _require_active(control)
        response = self._run_worker(
            {
                "operation": "discover_pages",
                "start_url": start_url.strip(),
                "max_visit_depth": max_visit_depth,
                "include_globs": list(include_globs),
                "exclude_globs": list(exclude_globs),
                "max_pages": discovery.max_pages,
                "max_candidates": discovery.max_candidates,
                "max_links_per_page": discovery.max_links_per_page,
                "max_result_chars": discovery.max_result_chars,
                "max_concurrency": discovery.max_concurrency,
                "max_tasks_per_minute": discovery.max_tasks_per_minute,
                "max_request_retries": discovery.max_request_retries,
                "max_crawl_seconds": discovery.max_crawl_seconds,
                "allow_query_links": discovery.allow_query_links,
                "max_source_bytes": self._settings.max_source_bytes,
                "request_timeout_seconds": self._settings.request_timeout_seconds,
                "max_redirects": self._settings.max_redirects,
                "user_agent": self._settings.user_agent,
            },
            control=control,
            stdout_limit=discovery.max_result_chars + 16_000,
        )
        full_payload = _discovery_payload(response, start_url=start_url.strip())
        if len(dumps_json(full_payload)) > discovery.max_result_chars:
            raise WebWorkerProtocolError(
                "Web discovery result violates result limits"
            )
        if len(dumps_json(full_payload)) <= discovery.max_inline_chars:
            return WebDiscoveryResult(payload=full_payload)

        target_link = _discovery_workspace_link(invoke_id, call_id)
        document = json.dumps(
            full_payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"
        _require_active(control)
        committed = self._workspace.write_bundle(
            (
                WorkspaceBundleWrite(
                    link=target_link,
                    data=document.encode("utf-8"),
                    retention=WorkspaceRetention.DAY,
                    owner_turn_id=owner_turn_id,
                ),
            )
        )
        preview = _discovery_preview_payload(
            full_payload,
            target_link=target_link,
            limit=discovery.max_inline_chars,
        )
        return WebDiscoveryResult(
            payload=preview,
            manifest=committed.manifest,
            record=committed.records[0],
        )

    def _run_worker(
        self,
        request: JsonObject,
        *,
        control: ActionExecutionControl,
        stdout_limit: int,
        include_kimi_key: bool = False,
    ) -> JsonObject:
        env = {
            name: self._runtime_env[name]
            for name in _SAFE_WORKER_ENV
            if self._runtime_env.get(name)
        }
        env["PYTHONIOENCODING"] = "utf-8"
        if include_kimi_key:
            env["TINYSOUL_KIMI_SEARCH_API_KEY"] = self._kimi_api_key
        outcome = self._process_runner.run(
            ProcessRequest(
                argv=(sys.executable, "-m", "tinysoul.capabilities.web.worker"),
                env=env,
                inherit_env=False,
                stdin_text=dumps_json(request),
                stdout_limit=stdout_limit,
                stderr_limit=_MAX_WORKER_STDERR,
            ),
            control,
        )
        if outcome.status is ProcessStatus.TIMED_OUT:
            raise WebProcessTimeout("Web worker timed out", reason="process_timeout")
        if outcome.status is ProcessStatus.CANCELLED:
            raise WebProcessTimeout(
                "Web worker was cancelled",
                reason=control.cancel_reason or "cancelled",
            )
        if outcome.status is ProcessStatus.START_FAILED:
            raise WebProcessingError(
                "Web worker failed to start",
                reason="process_start_failed",
                payload={"error_type": outcome.error_type},
            )
        _require_active(control)
        response = _worker_response(outcome.stdout)
        if outcome.exit_code != 0 or response.get("ok") is not True:
            reason = _optional_string(response, "reason") or "worker_failed"
            raise WebProcessingError(
                _optional_string(response, "message")
                or "Web worker could not complete the request",
                reason=reason,
                payload=_worker_failure_facts(response),
            )
        return response


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


def _discovery_workspace_link(invoke_id: str, call_id: str) -> str:
    identity = f"{invoke_id}-{call_id}"
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", identity).strip("-")[:80]
    if not normalized:
        normalized = sha256(identity.encode("utf-8")).hexdigest()[:24]
    return f"workspace:web/discovery/{normalized}.json"


def _search_markdown(
    *,
    query: str,
    answer: str,
    results: list[JsonObject],
) -> str:
    lines = ["# Web Search Result", "", "## Query", "", query, "", "## Answer", "", answer]
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
    preview = to_json_object({
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
    })
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
