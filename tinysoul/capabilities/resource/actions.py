"""ActionEngine integration for Resource conversion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from tinysoul.action import (
    ActionEngineBuilder,
    ActionExecution,
    ActionExecutionContext,
    ActionExecutor,
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


RESOURCE_MARKITDOWN_ACTION = "resource.convert_with_markitdown"
RESOURCE_PYPDF_ACTION = "resource.convert_with_pypdf"


@dataclass(frozen=True)
class _ConversionParams:
    source_link: str
    target_link: str
    overwrite: bool
    expected_source_digest: str
    expected_target_digest: str


class ResourceActionRuntimeBridge(Protocol):
    def trash_restore_required(self, *, link: str, trash_ref: str) -> RuntimeException:
        ...


class ResourceConversionExecutor(ActionExecutor):
    """Convert one document using a fixed local converter strategy."""

    def __init__(
        self,
        *,
        converter: ResourceConverter,
        service: ResourceConversionService,
        bus: SignalBus,
        runtime_bridge: ResourceActionRuntimeBridge | None = None,
    ) -> None:
        self._converter = converter
        self._service = service
        self._bus = bus
        self._runtime_bridge = runtime_bridge

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        params = _params(execution)
        if isinstance(params, ActionResult):
            return params
        try:
            result = self._service.convert(
                converter=self._converter,
                source_link=params.source_link,
                target_link=params.target_link,
                overwrite=params.overwrite,
                expected_source_digest=params.expected_source_digest,
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
        except ResourceProcessTimeout as exc:
            return ActionResult.timeout(
                call_id=execution.call.call_id,
                invoke_id=execution.framework.invoke_id,
                batch_id=execution.framework.batch_id,
                action_name=execution.call.action_name,
                sequence=execution.call.sequence,
                domain=execution.framework.domain,
                model_feedback=str(exc),
                frame_data={"reason": exc.reason, "executor_leaked": False},
            )
        except ResourceProcessingError as exc:
            return _failed(
                execution,
                str(exc),
                {**exc.payload, "reason": exc.reason},
            )
        except ResourceWorkerProtocolError:
            return _failed(
                execution,
                "Resource conversion returned an invalid staged result.",
                {"reason": "worker_protocol_invalid"},
            )
        except StagingError:
            return _failed(
                execution,
                "Resource conversion staging could not be completed.",
                {"reason": "staging_failed"},
            )
        except (ResourceContractError, WorkspaceError) as exc:
            return _failed(
                execution,
                "Resource conversion could not be completed.",
                {"reason": "resource_conversion_failed", "error_type": type(exc).__name__},
            )
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
    workspace: WorkspaceEngine,
    bus: SignalBus,
    staging: StagingDirectoryManager,
    runtime_bridge: ResourceActionRuntimeBridge | None = None,
    dependency_checker: DependencyChecker | None = None,
) -> ActionEngineBuilder:
    """Register enabled Resource executors and remove disabled catalog actions."""

    require_resource_dependencies(settings, checker=dependency_checker)
    markitdown = settings.convert_with_markitdown.enabled
    pypdf = settings.convert_with_pypdf.enabled
    if not markitdown:
        builder.disable_actions(RESOURCE_MARKITDOWN_ACTION)
    if not pypdf:
        builder.disable_actions(RESOURCE_PYPDF_ACTION)
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
        )
    return builder


def _params(execution: ActionExecution) -> _ConversionParams | ActionResult:
    source_link = execution.call.params.get("source_link")
    if not isinstance(source_link, str) or not source_link:
        return _failed(
            execution,
            f"{execution.call.action_name} requires a non-empty 'source_link'.",
            {"reason": "invalid_source_link"},
        )
    target_link = execution.call.params.get("target_link")
    if not isinstance(target_link, str) or not target_link:
        return _failed(
            execution,
            f"{execution.call.action_name} requires a non-empty 'target_link'.",
            {"reason": "invalid_target_link"},
        )
    overwrite = execution.call.params.get("overwrite", False)
    if not isinstance(overwrite, bool):
        return _failed(
            execution,
            "Resource conversion overwrite must be boolean.",
            {"reason": "invalid_overwrite"},
        )
    expected_source_digest = execution.call.params.get("expected_source_digest", "")
    if not isinstance(expected_source_digest, str):
        return _failed(
            execution,
            "Resource conversion expected_source_digest must be a string.",
            {"reason": "invalid_expected_source_digest"},
        )
    expected_target_digest = execution.call.params.get("expected_target_digest", "")
    if not isinstance(expected_target_digest, str):
        return _failed(
            execution,
            "Resource conversion expected_target_digest must be a string.",
            {"reason": "invalid_expected_target_digest"},
        )
    return _ConversionParams(
        source_link=source_link,
        target_link=target_link,
        overwrite=overwrite,
        expected_source_digest=expected_source_digest,
        expected_target_digest=expected_target_digest,
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
    frame_data: JsonObject,
) -> ActionResult:
    return ActionResult.failed(
        call_id=execution.call.call_id,
        invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id,
        action_name=execution.call.action_name,
        stage=ActionResultStage.EXECUTE,
        sequence=execution.call.sequence,
        domain=execution.framework.domain,
        model_feedback=model_feedback,
        frame_data=frame_data,
    )
