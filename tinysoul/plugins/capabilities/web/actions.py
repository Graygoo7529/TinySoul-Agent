"""ActionEngine integration for Web search and page extraction."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from tinysoul.infra import (
    DependencyChecker,
    JsonObject,
    StagingDirectoryManager,
    StagingError,
)
from tinysoul.kernel.action import (
    ActionEngineBuilder,
    ActionExecution,
    ActionExecutionContext,
    ActionExecutor,
    ActionLocalFailure,
    ActionResult,
    ActionResultStage,
)
from tinysoul.plugins.workspace import (
    WorkspaceContractError,
    WorkspaceError,
)
from tinysoul.plugins.workspace.runtime_bridge import RuntimeWorkspaceBridge
from tinysoul.plugins.workspace.services import WorkspaceService
from tinysoul.prompts.plugins.capabilities import web as prompt_text

from .config import WebSettings
from .dependencies import kimi_search_api_key, require_web_dependencies
from .errors import (
    WebContractError,
    WebProcessingError,
    WebProcessTimeout,
    WebWorkerProtocolError,
    web_failure_disposition,
)
from .models import (
    WebExtractor,
    WebFetchResult,
)
from .service import WebCapabilityService

WEB_SEARCH_KIMI_ACTION = "web.search_by_kimi"
WEB_DISCOVER_PAGES_ACTION = "web.discover_pages"
WEB_FETCH_DEFUDDLE_ACTION = "web.fetch_with_defuddle"
WEB_FETCH_TRAFILATURA_ACTION = "web.fetch_with_trafilatura"

_CONSTRAINT_FEEDBACK_BY_REASON = {
    "invalid_url": prompt_text.WEB_REQUEST_REQUIRES_PUBLIC_HTTPS_URL,
    "unsupported_url_scheme": prompt_text.WEB_REQUEST_REQUIRES_PUBLIC_HTTPS_URL,
    "private_network_target": prompt_text.WEB_REQUEST_REQUIRES_PUBLIC_HTTPS_URL,
    "url_chars_limit_exceeded": prompt_text.WEB_REQUEST_EXCEEDS_A_CONFIGURED_LIMIT,
    "query_chars_limit_exceeded": prompt_text.WEB_REQUEST_EXCEEDS_A_CONFIGURED_LIMIT,
    "result_chars_limit_exceeded": prompt_text.WEB_REQUEST_EXCEEDS_A_CONFIGURED_LIMIT,
    "search_token_limit_exceeded": prompt_text.WEB_REQUEST_EXCEEDS_A_CONFIGURED_LIMIT,
    "source_bytes_limit_exceeded": prompt_text.WEB_REQUEST_EXCEEDS_A_CONFIGURED_LIMIT,
    "output_chars_limit_exceeded": prompt_text.WEB_REQUEST_EXCEEDS_A_CONFIGURED_LIMIT,
    "staged_result_bytes_limit_exceeded": prompt_text.WEB_REQUEST_EXCEEDS_A_CONFIGURED_LIMIT,
    "unsupported_content_type": prompt_text.WEB_PAGE_CONTENT_TYPE_IS_NOT_SUPPORTED,
    "invalid_redirect": prompt_text.WEB_REQUEST_CANNOT_FOLLOW_REDIRECT,
    "redirect_limit_exceeded": prompt_text.WEB_REQUEST_CANNOT_FOLLOW_REDIRECT,
    "discovery_scope_violation": prompt_text.WEB_DISCOVERY_REQUEST_IS_OUT_OF_SCOPE,
    "invalid_visit_depth": prompt_text.WEB_DISCOVERY_REQUEST_IS_OUT_OF_SCOPE,
    "visit_depth_limit_exceeded": prompt_text.WEB_DISCOVERY_REQUEST_IS_OUT_OF_SCOPE,
    "invalid_path_globs": prompt_text.WEB_DISCOVERY_REQUEST_IS_OUT_OF_SCOPE,
    "seed_disallowed_by_robots": prompt_text.WEB_DISCOVERY_SEED_IS_DISALLOWED,
}
_PROVIDER_FAILURE_REASONS = frozenset(
    {
        "provider_output_incomplete",
        "provider_protocol_invalid",
    }
)


@dataclass(frozen=True)
class _FetchParams:
    url: str
    target_link: str
    overwrite: bool


@dataclass(frozen=True)
class _DiscoveryParams:
    start_url: str
    max_visit_depth: int
    include_globs: tuple[str, ...]
    exclude_globs: tuple[str, ...]


class KimiSearchExecutor(ActionExecutor):
    """Run the independent Kimi Web Search provider loop."""

    def __init__(
        self,
        *,
        service: WebCapabilityService,
    ) -> None:
        self._service = service

    async def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        query = execution.call.params.get("query")
        if not isinstance(query, str) or not query.strip():
            return _failed(
                execution,
                prompt_text.KIMI_WEB_SEARCH_REQUIRES_A_NON_EMPTY_QUERY,
                reason="invalid_query",
            )
        try:
            result = await self._service.search_by_kimi(
                query=query,
                invoke_id=execution.framework.invoke_id,
                call_id=execution.call.call_id,
                control=context.control,
                operations=context.owner_operations,
            )
        except WebProcessTimeout as exc:
            return _timeout(execution, _timeout_feedback(exc.reason), reason=exc.reason)
        except WebProcessingError as exc:
            return _failed(
                execution,
                _processing_feedback(exc.reason),
                reason=exc.reason,
                frame_data=exc.payload,
            )
        except WebWorkerProtocolError:
            return _failed(
                execution,
                prompt_text.KIMI_WEB_SEARCH_RETURNED_AN_INVALID_BOUNDED_RESULT,
                reason="worker_protocol_invalid",
            )
        except StagingError:
            return _failed(
                execution,
                prompt_text.KIMI_WEB_SEARCH_STAGING_COULD_NOT_BE_COMPLETED,
                reason="staging_failed",
            )
        except (WebContractError, WorkspaceContractError) as exc:
            return _failed(
                execution,
                prompt_text.KIMI_WEB_SEARCH_COULD_NOT_BE_COMPLETED,
                reason="web_search_failed",
                frame_data={"error_type": type(exc).__name__},
            )
        except WorkspaceError as exc:
            raise RuntimeWorkspaceBridge().from_workspace_error(exc) from exc
        return _success(execution, result.payload)


class WebFetchExecutor(ActionExecutor):
    """Fetch one page with a fixed local extraction strategy."""

    def __init__(
        self,
        *,
        extractor: WebExtractor,
        service: WebCapabilityService,
        runtime_bridge: RuntimeWorkspaceBridge | None = None,
    ) -> None:
        self._extractor = extractor
        self._service = service
        self._runtime_bridge = runtime_bridge

    async def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        params = _fetch_params(execution)
        if isinstance(params, ActionResult):
            return params
        try:
            result = await self._service.fetch(
                extractor=self._extractor,
                url=params.url,
                target_link=params.target_link,
                overwrite=params.overwrite,
                control=context.control,
                operations=context.owner_operations,
            )
        except WebProcessTimeout as exc:
            return _timeout(execution, _timeout_feedback(exc.reason), reason=exc.reason)
        except WebProcessingError as exc:
            return _failed(
                execution,
                _processing_feedback(exc.reason),
                reason=exc.reason,
                frame_data=exc.payload,
            )
        except WebWorkerProtocolError:
            return _failed(
                execution,
                prompt_text.WEB_FETCH_RETURNED_AN_INVALID_STAGED_RESULT,
                reason="worker_protocol_invalid",
            )
        except StagingError:
            return _failed(
                execution,
                prompt_text.WEB_FETCH_STAGING_COULD_NOT_BE_COMPLETED,
                reason="staging_failed",
            )
        except (WebContractError, WorkspaceContractError) as exc:
            return _failed(
                execution,
                prompt_text.WEB_FETCH_COULD_NOT_BE_COMPLETED,
                reason="web_fetch_failed",
                frame_data={"error_type": type(exc).__name__},
            )
        except WorkspaceError as exc:
            raise RuntimeWorkspaceBridge().from_workspace_error(exc) from exc
        return _success(execution, _fetch_payload(result))


class WebDiscoveryExecutor(ActionExecutor):
    """Discover same-origin page candidates through the bounded Web service."""

    def __init__(
        self,
        *,
        service: WebCapabilityService,
    ) -> None:
        self._service = service

    async def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        params = _discovery_params(execution)
        if isinstance(params, ActionResult):
            return params
        try:
            result = await self._service.discover_pages(
                start_url=params.start_url,
                max_visit_depth=params.max_visit_depth,
                include_globs=params.include_globs,
                exclude_globs=params.exclude_globs,
                invoke_id=execution.framework.invoke_id,
                call_id=execution.call.call_id,
                control=context.control,
                operations=context.owner_operations,
            )
        except WebProcessTimeout as exc:
            return _timeout(execution, _timeout_feedback(exc.reason), reason=exc.reason)
        except WebProcessingError as exc:
            return _failed(
                execution,
                _processing_feedback(exc.reason),
                reason=exc.reason,
                frame_data=exc.payload,
            )
        except WebWorkerProtocolError:
            return _failed(
                execution,
                prompt_text.WEB_PAGE_DISCOVERY_RETURNED_AN_INVALID_BOUNDED_RESULT,
                reason="worker_protocol_invalid",
            )
        except StagingError:
            return _failed(
                execution,
                prompt_text.WEB_PAGE_DISCOVERY_STAGING_COULD_NOT_BE_COMPLETED,
                reason="staging_failed",
            )
        except (WebContractError, WorkspaceContractError) as exc:
            return _failed(
                execution,
                prompt_text.WEB_PAGE_DISCOVERY_COULD_NOT_BE_COMPLETED,
                reason="web_discovery_failed",
                frame_data={"error_type": type(exc).__name__},
            )
        except WorkspaceError as exc:
            raise RuntimeWorkspaceBridge().from_workspace_error(exc) from exc
        return _success(execution, result.payload)


def register_web_actions(
    builder: ActionEngineBuilder,
    *,
    settings: WebSettings,
    runtime_env: Mapping[str, str],
    workspace: WorkspaceService,
    staging: StagingDirectoryManager,
    runtime_bridge: RuntimeWorkspaceBridge | None = None,
    dependency_checker: DependencyChecker | None = None,
) -> ActionEngineBuilder:
    """Register enabled Web executors and declare runtime support."""

    require_web_dependencies(settings, checker=dependency_checker)
    search_enabled = settings.search_by_kimi.enabled
    discovery_enabled = settings.discover_pages.enabled
    defuddle_enabled = settings.fetch_with_defuddle.enabled
    trafilatura_enabled = settings.fetch_with_trafilatura.enabled
    if not search_enabled:
        builder.mark_actions_unsupported(WEB_SEARCH_KIMI_ACTION)
    if not discovery_enabled:
        builder.mark_actions_unsupported(WEB_DISCOVER_PAGES_ACTION)
    if not defuddle_enabled:
        builder.mark_actions_unsupported(WEB_FETCH_DEFUDDLE_ACTION)
    if not trafilatura_enabled:
        builder.mark_actions_unsupported(WEB_FETCH_TRAFILATURA_ACTION)
    if (
        not search_enabled
        and not discovery_enabled
        and not defuddle_enabled
        and not trafilatura_enabled
    ):
        return builder
    service = WebCapabilityService(
        workspace=workspace,
        settings=settings,
        runtime_env=runtime_env,
        staging=staging,
        kimi_api_key=kimi_search_api_key(settings, runtime_env),
    )
    if search_enabled:
        builder.register_executor(
            WEB_SEARCH_KIMI_ACTION,
            KimiSearchExecutor(service=service),
        )
    if discovery_enabled:
        builder.register_executor(
            WEB_DISCOVER_PAGES_ACTION,
            WebDiscoveryExecutor(service=service),
        )
    if defuddle_enabled:
        builder.register_executor(
            WEB_FETCH_DEFUDDLE_ACTION,
            WebFetchExecutor(
                extractor=WebExtractor.DEFUDDLE,
                service=service,
                runtime_bridge=runtime_bridge,
            ),
        )
    if trafilatura_enabled:
        builder.register_executor(
            WEB_FETCH_TRAFILATURA_ACTION,
            WebFetchExecutor(
                extractor=WebExtractor.TRAFILATURA,
                service=service,
                runtime_bridge=runtime_bridge,
            ),
        )
    return builder


def _fetch_params(execution: ActionExecution) -> _FetchParams | ActionResult:
    url = execution.call.params.get("url")
    if not isinstance(url, str) or not url:
        return _failed(
            execution,
            prompt_text.url_required(action_name=execution.call.action_name),
            reason="invalid_url",
        )
    target_link = execution.call.params.get("target_link")
    if not isinstance(target_link, str) or not target_link:
        return _failed(
            execution,
            prompt_text.target_link_required(action_name=execution.call.action_name),
            reason="invalid_target_link",
        )
    overwrite = execution.call.params.get("overwrite", False)
    if not isinstance(overwrite, bool):
        return _failed(
            execution,
            prompt_text.WEB_FETCH_OVERWRITE_MUST_BE_BOOLEAN,
            reason="invalid_overwrite",
        )
    return _FetchParams(
        url=url,
        target_link=target_link,
        overwrite=overwrite,
    )


def _discovery_params(
    execution: ActionExecution,
) -> _DiscoveryParams | ActionResult:
    start_url = execution.call.params.get("start_url")
    if not isinstance(start_url, str) or not start_url.strip():
        return _failed(
            execution,
            prompt_text.WEB_PAGE_DISCOVERY_REQUIRES_A_NON_EMPTY_START_URL,
            reason="invalid_start_url",
        )
    max_visit_depth = execution.call.params.get("max_visit_depth", 0)
    if (
        isinstance(max_visit_depth, bool)
        or not isinstance(max_visit_depth, int)
        or max_visit_depth < 0
    ):
        return _failed(
            execution,
            prompt_text.INVALID_DISCOVERY_DEPTH,
            reason="invalid_visit_depth",
        )
    include_globs = _string_tuple_param(execution, "include_globs")
    if isinstance(include_globs, ActionResult):
        return include_globs
    exclude_globs = _string_tuple_param(execution, "exclude_globs")
    if isinstance(exclude_globs, ActionResult):
        return exclude_globs
    return _DiscoveryParams(
        start_url=start_url.strip(),
        max_visit_depth=max_visit_depth,
        include_globs=include_globs,
        exclude_globs=exclude_globs,
    )


def _string_tuple_param(
    execution: ActionExecution,
    name: str,
) -> tuple[str, ...] | ActionResult:
    value = execution.call.params.get(name, [])
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        return _failed(
            execution,
            prompt_text.discovery_patterns_required(name=name),
            reason="invalid_path_globs",
        )
    return tuple(cast(list[str], value))


def _fetch_payload(result: WebFetchResult) -> JsonObject:
    return {
        "markdown_link": result.markdown_link,
        "extractor": result.extractor.value,
        "title": result.title,
        "excerpt": result.excerpt,
        "content_chars": result.content_chars,
        "remote_image_count": result.remote_image_count,
        "untrusted_external_content": True,
        "warning_codes": list(result.warning_codes),
    }


def _success(execution: ActionExecution, payload: JsonObject) -> ActionResult:
    return ActionResult.success(
        call_id=execution.call.call_id,
        invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id,
        action_name=execution.call.action_name,
        sequence=execution.call.sequence,
        domain=execution.framework.domain,
        payload=payload,
    )


def _processing_feedback(reason: str) -> str:
    if reason in _PROVIDER_FAILURE_REASONS:
        return prompt_text.WEB_PROVIDER_RETURNED_AN_INVALID_RESULT
    return _CONSTRAINT_FEEDBACK_BY_REASON.get(
        reason,
        prompt_text.WEB_ACTION_COULD_NOT_BE_COMPLETED,
    )


def _timeout_feedback(reason: str) -> str:
    if reason in {"process_timeout", "deadline_expired"}:
        return prompt_text.WEB_ACTION_TIMED_OUT
    return prompt_text.WEB_ACTION_WAS_CANCELLED


def _failed(
    execution: ActionExecution,
    model_feedback: str,
    *,
    reason: str,
    frame_data: JsonObject | None = None,
) -> ActionResult:
    diagnostics = frame_data or {}
    return ActionResult.failed(
        call_id=execution.call.call_id,
        invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id,
        action_name=execution.call.action_name,
        stage=ActionResultStage.EXECUTE,
        sequence=execution.call.sequence,
        domain=execution.framework.domain,
        failure=ActionLocalFailure(
            reason=reason,
            scope="web.execution",
            disposition=web_failure_disposition(reason, diagnostics),
            feedback=model_feedback,
        ),
        frame_data=diagnostics,
    )


def _timeout(
    execution: ActionExecution,
    model_feedback: str,
    *,
    reason: str,
) -> ActionResult:
    frame_data: JsonObject = {"executor_leaked": False}
    return ActionResult.timeout(
        call_id=execution.call.call_id,
        invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id,
        action_name=execution.call.action_name,
        sequence=execution.call.sequence,
        domain=execution.framework.domain,
        failure=ActionLocalFailure(
            reason=reason,
            scope="web.execution",
            disposition=web_failure_disposition(reason, frame_data),
            feedback=model_feedback,
        ),
        frame_data=frame_data,
    )
