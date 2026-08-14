"""ActionEngine integration for Web search and page extraction."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, cast

from tinysoul.action import (
    ActionEngineBuilder,
    ActionExecution,
    ActionExecutionContext,
    ActionExecutor,
    ActionLocalFailure,
    ActionResult,
    ActionResultStage,
)
from tinysoul.infra import (
    DependencyChecker,
    JsonObject,
    StagingDirectoryManager,
    StagingError,
)
from tinysoul.runtime import RuntimeException, SignalBus
from tinysoul.workspace import (
    WorkspaceError,
    WorkspaceEngine,
    WorkspaceTrashRestoreRequired,
    workspace_snapshot_signal,
)

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
    WebDiscoveryResult,
    WebExtractor,
    WebFetchResult,
    WebSearchResult,
)
from .service import WebCapabilityService


WEB_SEARCH_KIMI_ACTION = "web.search_by_kimi"
WEB_DISCOVER_PAGES_ACTION = "web.discover_pages"
WEB_FETCH_DEFUDDLE_ACTION = "web.fetch_with_defuddle"
WEB_FETCH_TRAFILATURA_ACTION = "web.fetch_with_trafilatura"


@dataclass(frozen=True)
class _FetchParams:
    url: str
    target_link: str
    overwrite: bool
    expected_target_digest: str


@dataclass(frozen=True)
class _DiscoveryParams:
    start_url: str
    max_visit_depth: int
    include_globs: tuple[str, ...]
    exclude_globs: tuple[str, ...]


class WebActionRuntimeBridge(Protocol):
    def trash_restore_required(self, *, link: str, trash_ref: str) -> RuntimeException:
        ...


class KimiSearchExecutor(ActionExecutor):
    """Run the independent Kimi Web Search provider loop."""

    def __init__(
        self,
        *,
        service: WebCapabilityService,
        bus: SignalBus,
    ) -> None:
        self._service = service
        self._bus = bus

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        query = execution.call.params.get("query")
        if not isinstance(query, str) or not query.strip():
            return _failed(
                execution,
                "Kimi Web Search requires a non-empty 'query'.",
                reason="invalid_query",
            )
        try:
            result = self._service.search_by_kimi(
                query=query,
                invoke_id=execution.framework.invoke_id,
                call_id=execution.call.call_id,
                owner_turn_id=execution.framework.turn_id,
                control=context.control,
            )
        except WebProcessTimeout as exc:
            return _timeout(execution, str(exc), reason=exc.reason)
        except WebProcessingError as exc:
            return _failed(execution, str(exc), reason=exc.reason, frame_data=exc.payload)
        except WebWorkerProtocolError:
            return _failed(
                execution,
                "Kimi Web Search returned an invalid bounded result.",
                reason="worker_protocol_invalid",
            )
        except StagingError:
            return _failed(
                execution,
                "Kimi Web Search staging could not be completed.",
                reason="staging_failed",
            )
        except (WebContractError, WorkspaceError) as exc:
            return _failed(
                execution,
                "Kimi Web Search could not be completed.",
                reason="web_search_failed",
                frame_data={"error_type": type(exc).__name__},
            )
        _emit_search_snapshot(execution, context, self._bus, result)
        return _success(execution, result.payload)


class WebFetchExecutor(ActionExecutor):
    """Fetch one page with a fixed local extraction strategy."""

    def __init__(
        self,
        *,
        extractor: WebExtractor,
        service: WebCapabilityService,
        bus: SignalBus,
        runtime_bridge: WebActionRuntimeBridge | None = None,
    ) -> None:
        self._extractor = extractor
        self._service = service
        self._bus = bus
        self._runtime_bridge = runtime_bridge

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        params = _fetch_params(execution)
        if isinstance(params, ActionResult):
            return params
        try:
            result = self._service.fetch(
                extractor=self._extractor,
                url=params.url,
                target_link=params.target_link,
                overwrite=params.overwrite,
                expected_target_digest=params.expected_target_digest,
                owner_turn_id=execution.framework.turn_id,
                control=context.control,
            )
        except WorkspaceTrashRestoreRequired as exc:
            if self._runtime_bridge is None:
                raise
            raise self._runtime_bridge.trash_restore_required(
                link=exc.link,
                trash_ref=exc.trash_ref,
            ) from exc
        except WebProcessTimeout as exc:
            return _timeout(execution, str(exc), reason=exc.reason)
        except WebProcessingError as exc:
            return _failed(execution, str(exc), reason=exc.reason, frame_data=exc.payload)
        except WebWorkerProtocolError:
            return _failed(
                execution,
                "Web fetch returned an invalid staged result.",
                reason="worker_protocol_invalid",
            )
        except StagingError:
            return _failed(
                execution,
                "Web fetch staging could not be completed.",
                reason="staging_failed",
            )
        except (WebContractError, WorkspaceError) as exc:
            return _failed(
                execution,
                "Web fetch could not be completed.",
                reason="web_fetch_failed",
                frame_data={"error_type": type(exc).__name__},
            )
        _emit_fetch_snapshot(execution, context, self._bus, result)
        return _success(execution, _fetch_payload(result))


class WebDiscoveryExecutor(ActionExecutor):
    """Discover same-origin page candidates through the bounded Web service."""

    def __init__(
        self,
        *,
        service: WebCapabilityService,
        bus: SignalBus,
    ) -> None:
        self._service = service
        self._bus = bus

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        params = _discovery_params(execution)
        if isinstance(params, ActionResult):
            return params
        try:
            result = self._service.discover_pages(
                start_url=params.start_url,
                max_visit_depth=params.max_visit_depth,
                include_globs=params.include_globs,
                exclude_globs=params.exclude_globs,
                invoke_id=execution.framework.invoke_id,
                call_id=execution.call.call_id,
                owner_turn_id=execution.framework.turn_id,
                control=context.control,
            )
        except WebProcessTimeout as exc:
            return _timeout(execution, str(exc), reason=exc.reason)
        except WebProcessingError as exc:
            return _failed(execution, str(exc), reason=exc.reason, frame_data=exc.payload)
        except WebWorkerProtocolError:
            return _failed(
                execution,
                "Web page discovery returned an invalid bounded result.",
                reason="worker_protocol_invalid",
            )
        except StagingError:
            return _failed(
                execution,
                "Web page discovery staging could not be completed.",
                reason="staging_failed",
            )
        except (WebContractError, WorkspaceError) as exc:
            return _failed(
                execution,
                "Web page discovery could not be completed.",
                reason="web_discovery_failed",
                frame_data={"error_type": type(exc).__name__},
            )
        _emit_discovery_snapshot(execution, context, self._bus, result)
        return _success(execution, result.payload)


def register_web_actions(
    builder: ActionEngineBuilder,
    *,
    settings: WebSettings,
    runtime_env: Mapping[str, str],
    workspace: WorkspaceEngine,
    bus: SignalBus,
    staging: StagingDirectoryManager,
    runtime_bridge: WebActionRuntimeBridge | None = None,
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
            KimiSearchExecutor(service=service, bus=bus),
        )
    if discovery_enabled:
        builder.register_executor(
            WEB_DISCOVER_PAGES_ACTION,
            WebDiscoveryExecutor(service=service, bus=bus),
        )
    if defuddle_enabled:
        builder.register_executor(
            WEB_FETCH_DEFUDDLE_ACTION,
            WebFetchExecutor(
                extractor=WebExtractor.DEFUDDLE,
                service=service,
                bus=bus,
                runtime_bridge=runtime_bridge,
            ),
        )
    if trafilatura_enabled:
        builder.register_executor(
            WEB_FETCH_TRAFILATURA_ACTION,
            WebFetchExecutor(
                extractor=WebExtractor.TRAFILATURA,
                service=service,
                bus=bus,
                runtime_bridge=runtime_bridge,
            ),
        )
    return builder


def _fetch_params(execution: ActionExecution) -> _FetchParams | ActionResult:
    url = execution.call.params.get("url")
    if not isinstance(url, str) or not url:
        return _failed(
            execution,
            f"{execution.call.action_name} requires a non-empty 'url'.",
            reason="invalid_url",
        )
    target_link = execution.call.params.get("target_link")
    if not isinstance(target_link, str) or not target_link:
        return _failed(
            execution,
            f"{execution.call.action_name} requires a non-empty 'target_link'.",
            reason="invalid_target_link",
        )
    overwrite = execution.call.params.get("overwrite", False)
    if not isinstance(overwrite, bool):
        return _failed(
            execution,
            "Web fetch overwrite must be boolean.",
            reason="invalid_overwrite",
        )
    expected = execution.call.params.get("expected_target_digest", "")
    if not isinstance(expected, str):
        return _failed(
            execution,
            "Web fetch expected_target_digest must be a string.",
            reason="invalid_expected_target_digest",
        )
    return _FetchParams(
        url=url,
        target_link=target_link,
        overwrite=overwrite,
        expected_target_digest=expected,
    )


def _discovery_params(
    execution: ActionExecution,
) -> _DiscoveryParams | ActionResult:
    start_url = execution.call.params.get("start_url")
    if not isinstance(start_url, str) or not start_url.strip():
        return _failed(
            execution,
            "Web page discovery requires a non-empty 'start_url'.",
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
            "Web page discovery max_visit_depth must be a non-negative integer.",
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
            f"Web page discovery {name} must be an array of non-empty strings.",
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


def _emit_search_snapshot(
    execution: ActionExecution,
    context: ActionExecutionContext,
    bus: SignalBus,
    result: WebSearchResult,
) -> None:
    if result.manifest is None:
        return
    (context.signal_bus or bus).emit(
        workspace_snapshot_signal(
            result.manifest,
            call_id=execution.call.call_id,
            scope=execution.framework.scope,
            source=execution.call.action_name,
        )
    )


def _emit_discovery_snapshot(
    execution: ActionExecution,
    context: ActionExecutionContext,
    bus: SignalBus,
    result: WebDiscoveryResult,
) -> None:
    if result.manifest is None:
        return
    (context.signal_bus or bus).emit(
        workspace_snapshot_signal(
            result.manifest,
            call_id=execution.call.call_id,
            scope=execution.framework.scope,
            source=execution.call.action_name,
        )
    )


def _emit_fetch_snapshot(
    execution: ActionExecution,
    context: ActionExecutionContext,
    bus: SignalBus,
    result: WebFetchResult,
) -> None:
    (context.signal_bus or bus).emit(
        workspace_snapshot_signal(
            result.manifest,
            call_id=execution.call.call_id,
            scope=execution.framework.scope,
            source=execution.call.action_name,
        )
    )


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
