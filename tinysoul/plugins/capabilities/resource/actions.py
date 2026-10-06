"""ActionEngine integration for Resource conversion."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.prompts.plugins.capabilities import resource as prompt_text
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
from tinysoul.plugins.workspace import (
    WorkspaceError,
    WorkspaceContractError,
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
    source_ref: str
    target_ref: str
    overwrite: bool


class ResourceConversionExecutor(ActionExecutor):
    """Convert one document using a fixed local converter strategy."""

    def __init__(
        self,
        *,
        converter: ResourceConverter,
        service: ResourceConversionService,
        runtime_bridge: RuntimeWorkspaceBridge | None = None,
    ) -> None:
        self._converter = converter
        self._service = service
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
                source_ref=params.source_ref,
                target_ref=params.target_ref,
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
                prompt_text.INVALID_CONVERSION_RESULT,
                reason="worker_protocol_invalid",
                disposition=ActionFailureDisposition.STOP,
            )
        except StagingError:
            return _failed(
                execution,
                prompt_text.CONVERSION_STAGING_FAILED,
                reason="staging_failed",
                disposition=ActionFailureDisposition.STOP,
            )
        except (ResourceContractError, WorkspaceContractError) as exc:
            return _failed(
                execution,
                prompt_text.RESOURCE_CONVERSION_COULD_NOT_BE_COMPLETED,
                reason="resource_conversion_failed",
                frame_data={"error_type": type(exc).__name__},
            )
        except WorkspaceError as exc:
            raise RuntimeWorkspaceBridge().from_workspace_error(exc) from exc
        return _success(execution, _result_payload(result))


def register_resource_actions(
    builder: ActionEngineBuilder,
    *,
    settings: ResourceSettings,
    workspace: WorkspaceService,
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
                runtime_bridge=runtime_bridge,
            ),
            executor_id=_RESOURCE_MARKITDOWN_HANDLER,
        )
    if pypdf:
        builder.register_executor(
            RESOURCE_PYPDF_ACTION,
            ResourceConversionExecutor(
                converter=ResourceConverter.PYPDF,
                service=service,
                runtime_bridge=runtime_bridge,
            ),
            executor_id=_RESOURCE_PYPDF_HANDLER,
        )
    return builder


def _params(execution: ActionExecution) -> _ConversionParams | ActionResult:
    source_ref = execution.call.params.get("source_ref")
    if not isinstance(source_ref, str) or not source_ref:
        return _failed(
            execution,
            prompt_text.source_ref_required(action_name=execution.call.action_name),
            reason="invalid_source_ref",
        )
    target_ref = execution.call.params.get("target_ref")
    if not isinstance(target_ref, str) or not target_ref:
        return _failed(
            execution,
            prompt_text.target_ref_required(action_name=execution.call.action_name),
            reason="invalid_target_ref",
        )
    overwrite = execution.call.params.get("overwrite", False)
    if not isinstance(overwrite, bool):
        return _failed(
            execution,
            prompt_text.RESOURCE_CONVERSION_OVERWRITE_MUST_BE_BOOLEAN,
            reason="invalid_overwrite",
        )
    return _ConversionParams(
        source_ref=source_ref,
        target_ref=target_ref,
        overwrite=overwrite,
    )


def _result_payload(result: ResourceConversionResult) -> JsonObject:
    return {
        "source_ref": result.source_ref,
        "markdown_ref": result.markdown_ref,
        "converter": result.converter.value,
        "content_status": result.content_status.value,
        "generated_resource_count": len(result.records),
        "visual_review_required": bool(result.visual_refs),
        "visual_refs": list(result.visual_refs),
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
