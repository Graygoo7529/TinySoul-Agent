"""ActionEngine integration for Resource conversion."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.kernel.action import (
    ActionEngineBuilder,
    ActionExecution,
    ActionExecutionContext,
    ActionExecutor,
    ActionFailureDisposition,
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
from tinysoul.runtime import SignalBus
from tinysoul.plugins.workspace import (
    WorkspaceError,
    WorkspaceContractError,
    workspace_snapshot_signal,
)

from tinysoul.plugins.workspace.services import WorkspaceService
from tinysoul.plugins.workspace.runtime_bridge import RuntimeWorkspaceBridge
from .config import ResourceSettings
from .dependencies import require_resource_dependencies
from .errors import (
    ResourceContractError,
    ResourceProcessingError,
    ResourceProcessTimeout,
    ResourceWorkerProtocolError,
)
from .models import ResourceConversionResult, ResourceConverter
from .service import ResourceConversionService

RESOURCE_MARKITDOWN_ACTION = "workspace.convert_with_markitdown"
RESOURCE_PYPDF_ACTION = "workspace.convert_with_pypdf"
_RESOURCE_MARKITDOWN_HANDLER = "resource.convert_with_markitdown"
_RESOURCE_PYPDF_HANDLER = "resource.convert_with_pypdf"


@dataclass(frozen=True)
class _ConversionParams:
    source_link: str
    target_link: str
    overwrite: bool


class ResourceConversionExecutor(ActionExecutor):
    """Convert one document using a fixed local converter strategy."""

    def __init__(
        self,
        *,
        converter: ResourceConverter,
        service: ResourceConversionService,
        bus: SignalBus,
        runtime_bridge: RuntimeWorkspaceBridge | None = None,
    ) -> None:
        self._converter = converter
        self._service = service
        self._bus = bus
        self._runtime_bridge = runtime_bridge

    async def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        params = _params(execution)
        if isinstance(params, ActionResult):
            return params
        try:
            result = await self._service.convert(
                converter=self._converter,
                source_link=params.source_link,
                target_link=params.target_link,
                overwrite=params.overwrite,
                control=context.control,
                operations=context.owner_operations,
            )
        except ResourceProcessTimeout as exc:
            return ActionResult.timeout(
                call_id=execution.call.call_id,
                invoke_id=execution.framework.invoke_id,
                batch_id=execution.framework.batch_id,
                action_name=execution.call.action_name,
                sequence=execution.call.sequence,
                domain=execution.framework.domain,
                failure=ActionLocalFailure(
                    reason=exc.reason,
                    scope="resource.conversion",
                    disposition=ActionFailureDisposition.RETRY_SAME,
                    feedback=str(exc),
                ),
                frame_data={"executor_leaked": False},
            )
        except ResourceProcessingError as exc:
            return _failed(
                execution,
                str(exc),
                reason=exc.reason,
                frame_data=exc.payload,
            )
        except ResourceWorkerProtocolError:
            return _failed(
                execution,
                "Resource conversion returned an invalid staged result.",
                reason="worker_protocol_invalid",
                disposition=ActionFailureDisposition.STOP,
            )
        except StagingError:
            return _failed(
                execution,
                "Resource conversion staging could not be completed.",
                reason="staging_failed",
                disposition=ActionFailureDisposition.STOP,
            )
        except (ResourceContractError, WorkspaceContractError) as exc:
            return _failed(
                execution,
                "Resource conversion could not be completed.",
                reason="resource_conversion_failed",
                frame_data={"error_type": type(exc).__name__},
            )
        except WorkspaceError as exc:
            raise RuntimeWorkspaceBridge().from_workspace_error(exc) from exc
        signal_bus = context.signal_bus or self._bus
        signal_bus.emit(
            workspace_snapshot_signal(
                result.manifest,
                call_id=execution.call.call_id,
                scope=execution.framework.scope,
                source=execution.call.action_name,
            )
        )
        return _success(execution, _result_payload(result))


def register_resource_actions(
    builder: ActionEngineBuilder,
    *,
    settings: ResourceSettings,
    workspace: WorkspaceService,
    bus: SignalBus,
    staging: StagingDirectoryManager,
    runtime_bridge: RuntimeWorkspaceBridge | None = None,
    dependency_checker: DependencyChecker | None = None,
) -> ActionEngineBuilder:
    """Register enabled Resource executors and declare runtime support."""

    require_resource_dependencies(settings, checker=dependency_checker)
    markitdown = settings.convert_with_markitdown.enabled
    pypdf = settings.convert_with_pypdf.enabled
    if not markitdown:
        builder.mark_actions_unsupported(RESOURCE_MARKITDOWN_ACTION)
    if not pypdf:
        builder.mark_actions_unsupported(RESOURCE_PYPDF_ACTION)
    if not markitdown and not pypdf:
        return builder
    service = ResourceConversionService(
        workspace=workspace,
        settings=settings,
        staging=staging,
    )
    if markitdown:
        builder.register_executor(
            RESOURCE_MARKITDOWN_ACTION,
            ResourceConversionExecutor(
                converter=ResourceConverter.MARKITDOWN,
                service=service,
                bus=bus,
                runtime_bridge=runtime_bridge,
            ),
            handler=_RESOURCE_MARKITDOWN_HANDLER,
        )
    if pypdf:
        builder.register_executor(
            RESOURCE_PYPDF_ACTION,
            ResourceConversionExecutor(
                converter=ResourceConverter.PYPDF,
                service=service,
                bus=bus,
                runtime_bridge=runtime_bridge,
            ),
            handler=_RESOURCE_PYPDF_HANDLER,
        )
    return builder


def _params(execution: ActionExecution) -> _ConversionParams | ActionResult:
    source_link = execution.call.params.get("source_link")
    if not isinstance(source_link, str) or not source_link:
        return _failed(
            execution,
            f"{execution.call.action_name} requires a non-empty 'source_link'.",
            reason="invalid_source_link",
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
            "Resource conversion overwrite must be boolean.",
            reason="invalid_overwrite",
        )
    return _ConversionParams(
        source_link=source_link,
        target_link=target_link,
        overwrite=overwrite,
    )


def _result_payload(result: ResourceConversionResult) -> JsonObject:
    return {
        "source_link": result.source_link,
        "markdown_link": result.markdown_link,
        "converter": result.converter.value,
        "content_status": result.content_status.value,
        "generated_resource_count": len(result.records),
        "visual_review_required": bool(result.visual_reference_links),
        "visual_reference_links": list(result.visual_reference_links),
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


def _failed(
    execution: ActionExecution,
    model_feedback: str,
    *,
    reason: str,
    disposition: ActionFailureDisposition = ActionFailureDisposition.CHANGE_REQUEST,
    frame_data: JsonObject | None = None,
) -> ActionResult:
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
            scope="resource.conversion",
            disposition=disposition,
            feedback=model_feedback,
        ),
        frame_data=frame_data,
    )
