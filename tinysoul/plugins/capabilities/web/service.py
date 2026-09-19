"""Web capability orchestration across worker and Workspace boundaries."""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
import shutil
import sys

from tinysoul.kernel.action import ActionExecutionControl
from tinysoul.kernel.action.backends import (
    ControlledProcessRunner,
    ProcessRequest,
    ProcessStatus,
)
from tinysoul.infra import (
    JsonObject,
    StagingDirectoryManager,
    dumps_json,
    to_json_object,
)
from tinysoul.plugins.workspace import (
    WorkspaceBundleWrite,
    WorkspaceLink,
)

from tinysoul.plugins.workspace.services import WorkspaceService
from tinysoul.infra.concurrency import JoinedOperations
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


from .operations.protocol import (
    _require_active,
    _worker_failure_facts,
    _worker_response,
    _required_string,
    _optional_string,
    _optional_object,
    _required_non_negative_int,
    _warning_codes,
)
from .operations.search import (
    _search_results,
    _search_workspace_link,
    _search_markdown,
    _search_preview_payload,
)
from .operations.discovery import (
    _discovery_workspace_link,
    _discovery_payload,
    _discovery_preview_payload,
    _validate_discovery_globs,
)


class WebCapabilityService:
    """Run Web operations in a fixed worker and commit bounded artifacts."""

    def __init__(
        self,
        *,
        workspace: WorkspaceService,
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
            shutil.which("defuddle", path=self._runtime_env.get("PATH")) or "defuddle"
        )

    async def search_by_kimi(
        self,
        *,
        query: str,
        invoke_id: str,
        call_id: str,
        control: ActionExecutionControl,
        operations: JoinedOperations | None = None,
    ) -> WebSearchResult:
        """Return answer and sources inline, spilling only oversized output."""

        operations = operations or JoinedOperations()
        workspace = self._workspace.using(operations)

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
        if not self._kimi_api_key:
            raise WebProcessingError(
                "Kimi Search credential is unavailable",
                reason="credential_unavailable",
            )
        _require_active(control)
        response = await operations.run(
            lambda: self._run_worker(
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
        committed = await workspace.write_bundle(
            (
                WorkspaceBundleWrite(
                    link=target_link,
                    data=markdown.encode("utf-8"),
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

    async def fetch(
        self,
        *,
        extractor: WebExtractor,
        url: str,
        target_link: str,
        overwrite: bool,
        control: ActionExecutionControl,
        operations: JoinedOperations | None = None,
    ) -> WebFetchResult:
        """Fetch and extract one public page into Workspace Markdown."""

        operations = operations or JoinedOperations()
        workspace = self._workspace.using(operations)

        if not isinstance(extractor, WebExtractor):
            raise WebContractError("Web extractor is invalid")
        if not isinstance(url, str) or not url:
            raise WebContractError("Web fetch URL must be non-empty")
        target = WorkspaceLink.parse(target_link)
        if target.path.suffix.lower() != ".md":
            raise WebContractError("Web fetch target must end with .md")
        if not isinstance(overwrite, bool):
            raise WebContractError("Web fetch overwrite must be boolean")
        _require_active(control)
        async with self._staging.allocate_async("web", operations) as output_path:
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
            response = await operations.run(
                lambda: self._run_worker(
                    worker_request,
                    control=control,
                    stdout_limit=32_000,
                )
            )
            markdown_file = _required_string(response, "markdown_file")
            if Path(markdown_file).name != markdown_file:
                raise WebWorkerProtocolError("Web worker Markdown path is invalid")
            markdown_path = output_path / markdown_file
            try:
                data = await operations.run(markdown_path.read_bytes)
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
            committed = await workspace.write_bundle(
                (
                    WorkspaceBundleWrite(
                        link=str(target),
                        data=data,
                        overwrite=overwrite,
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

    async def discover_pages(
        self,
        *,
        start_url: str,
        max_visit_depth: int,
        include_globs: tuple[str, ...],
        exclude_globs: tuple[str, ...],
        invoke_id: str,
        call_id: str,
        control: ActionExecutionControl,
        operations: JoinedOperations | None = None,
    ) -> WebDiscoveryResult:
        """Discover bounded same-origin page candidates without saving bodies."""

        operations = operations or JoinedOperations()
        workspace = self._workspace.using(operations)

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
        _require_active(control)
        response = await operations.run(
            lambda: self._run_worker(
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
        )
        full_payload = _discovery_payload(response, start_url=start_url.strip())
        if len(dumps_json(full_payload)) > discovery.max_result_chars:
            raise WebWorkerProtocolError("Web discovery result violates result limits")
        if len(dumps_json(full_payload)) <= discovery.max_inline_chars:
            return WebDiscoveryResult(payload=full_payload)

        target_link = _discovery_workspace_link(invoke_id, call_id)
        document = (
            json.dumps(
                full_payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        _require_active(control)
        committed = await workspace.write_bundle(
            (
                WorkspaceBundleWrite(
                    link=target_link,
                    data=document.encode("utf-8"),
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
                argv=(
                    sys.executable,
                    "-m",
                    "tinysoul.plugins.capabilities.web.backends.worker",
                ),
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
