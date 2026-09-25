"""Agent Home action executors."""

from __future__ import annotations

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
from tinysoul.infra.json import JsonObject
from tinysoul.runtime import Signal
from ..background import HOME_CONTEXT_UPDATE
from tinysoul.plugins.home.runtime_bridge import RuntimeAgentHomeBridge

from ..services import HomeService
from ..errors import (
    AgentHomeError,
    AgentHomeContractError,
    AgentHomeInvariantError,
    AgentHomeRuntimeCopyRequired,
)
from tinysoul.kernel.action.tasks import ActionTaskFactory
from tinysoul.kernel.action import ActionTraceProjection
from tinysoul.kernel.retrieval.requests import parse_search_request
from tinysoul.kernel.retrieval.operations import SelectionInput
from tinysoul.kernel.retrieval.contracts import SearchFailure, SearchContext
from tinysoul.infra.continuation import ContinuationError
from tinysoul.infra.references import ReferenceError


def register_home_actions(
    builder: ActionEngineBuilder,
    *,
    home: HomeService,
    runtime_bridge: RuntimeAgentHomeBridge,
    tasks: ActionTaskFactory | None = None,
) -> ActionEngineBuilder:
    """Register Agent Home action executors on an action builder."""

    builder.register_executor(
        "home.search",
        HomeSearchExecutor(
            home,
            tasks=tasks,
            runtime_bridge=runtime_bridge,
        ),
    )
    builder.register_executor(
        "home.inspect",
        HomeInspectExecutor(home, runtime_bridge=runtime_bridge),
    )
    builder.register_executor(
        "home.resource.write",
        HomeResourceWriteExecutor(home, runtime_bridge),
    )
    builder.register_executor(
        "home.resource.patch",
        HomeResourcePatchExecutor(home, runtime_bridge),
    )
    builder.register_executor(
        "home.resource.delete",
        HomeResourceDeleteExecutor(home, runtime_bridge),
    )
    builder.register_executor(
        "home.top.write",
        HomeTopWriteExecutor(home, runtime_bridge),
    )
    builder.register_executor(
        "home.top.patch",
        HomeTopPatchExecutor(home, runtime_bridge),
    )
    builder.register_executor(
        "home.top.delete",
        HomeTopDeleteExecutor(home, runtime_bridge),
    )
    builder.register_executor(
        "home.prompt_mount.write",
        HomePromptMountWriteExecutor(home, runtime_bridge),
    )
    builder.register_executor(
        "home.prompt_mount.patch",
        HomePromptMountPatchExecutor(home, runtime_bridge),
    )
    return builder


class HomeSearchExecutor(ActionExecutor):
    def __init__(
        self,
        home: HomeService,
        *,
        tasks: ActionTaskFactory | None = None,
        runtime_bridge: RuntimeAgentHomeBridge | None = None,
    ) -> None:
        self._home, self._tasks = home, tasks
        self._runtime_bridge = runtime_bridge or RuntimeAgentHomeBridge()

    async def execute(
        self, execution: ActionExecution, context: ActionExecutionContext
    ) -> ActionResult:
        home = self._home.using(context.owner_operations)
        try:
            request = parse_search_request(execution.call.params, home.search_policies)
            inputs = SelectionInput()
            if not isinstance(request, str) and self._tasks:
                inputs = await self._tasks.selection_input(
                    execution,
                    include_context=request.options.context is SearchContext.CURRENT,
                    control=context.control,
                )
            page = await home.search(request, inputs=inputs)
        except SearchFailure as exc:
            return _failed(execution, str(exc), reason=exc.kind.value)
        except AgentHomeContractError as exc:
            return _failed(execution, str(exc), reason="invalid_search")
        except AgentHomeError as exc:
            raise self._runtime_bridge.from_home_error(exc) from exc
        return ActionResult.success(
            call_id=execution.call.call_id,
            invoke_id=execution.framework.invoke_id,
            batch_id=execution.framework.batch_id,
            action_name=execution.call.action_name,
            sequence=execution.call.sequence,
            domain=execution.framework.domain,
            payload=page.to_json(),
            trace_projection=ActionTraceProjection(
                origin_refs=tuple(item.ref for item in page.items),
                canonical_payload={
                    "mode": page.mode.value,
                    "selected": [item.ref for item in page.items],
                },
            ),
        )


class HomeInspectExecutor(ActionExecutor):
    def __init__(
        self, home: HomeService, *, runtime_bridge: RuntimeAgentHomeBridge | None = None
    ) -> None:
        self._home = home
        self._runtime_bridge = runtime_bridge or RuntimeAgentHomeBridge()

    async def execute(
        self, execution: ActionExecution, context: ActionExecutionContext
    ) -> ActionResult:
        home = self._home.using(context.owner_operations)
        params = execution.call.params
        ref, view = params.get("ref"), params.get("view", "content")
        continuation, max_chars = params.get("continuation"), params.get("max_chars")
        if (
            not isinstance(ref, str)
            or not isinstance(view, str)
            or (continuation is not None and not isinstance(continuation, str))
            or (
                max_chars is not None and (type(max_chars) is not int or max_chars <= 0)
            )
        ):
            return _failed(
                execution,
                "Inspect requires a known ref and valid page options",
                reason="invalid_inspect",
            )
        try:
            page = await home.inspect(
                ref, view=view, continuation=continuation, max_chars=max_chars
            )
        except (
            SearchFailure,
            ContinuationError,
            AgentHomeContractError,
            ReferenceError,
        ) as exc:
            return _failed(execution, str(exc), reason="invalid_inspect")
        except AgentHomeError as exc:
            raise self._runtime_bridge.from_home_error(exc) from exc
        return ActionResult.success(
            call_id=execution.call.call_id,
            invoke_id=execution.framework.invoke_id,
            batch_id=execution.framework.batch_id,
            action_name=execution.call.action_name,
            sequence=execution.call.sequence,
            domain=execution.framework.domain,
            payload=page,
            trace_projection=ActionTraceProjection(
                origin_refs=(ref,), canonical_payload={"ref": ref, "view": view}
            ),
        )


class HomeResourceWriteExecutor(ActionExecutor):
    """Create or replace a progressive resource in the active Home overlay."""

    def __init__(
        self,
        home: HomeService,
        runtime_bridge: RuntimeAgentHomeBridge | None = None,
    ) -> None:
        self._home = home
        self._runtime_bridge = runtime_bridge or RuntimeAgentHomeBridge()

    async def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        home = self._home.using(context.owner_operations)
        link = execution.call.params.get("link")
        text = execution.call.params.get("text")
        overwrite = execution.call.params.get("overwrite", False)
        expected_digest = execution.call.params.get("expected_digest", "")
        if not isinstance(link, str) or not link or not isinstance(text, str):
            return _failed(
                execution,
                "home.resource.write requires non-empty 'link' and string 'text'.",
                reason="invalid_parameters",
            )
        if not isinstance(overwrite, bool) or not isinstance(expected_digest, str):
            return _failed(
                execution,
                "home.resource.write overwrite/expected_digest parameters are invalid.",
                reason="invalid_precondition",
            )
        try:
            result = await home.write_resource(
                link,
                text,
                overwrite=overwrite,
                expected_digest=expected_digest,
            )
        except AgentHomeContractError:
            return _failed(
                execution,
                "Home resource write request rejected; check the Link and current content.",
                reason="resource_write_failed",
            )
        except AgentHomeError as exc:
            raise self._runtime_bridge.from_home_error(exc) from exc
        return _mutation_success(execution, result)


class HomeResourcePatchExecutor(ActionExecutor):
    """Apply one deterministic exact replacement to the active Home overlay."""

    def __init__(
        self,
        home: HomeService,
        runtime_bridge: RuntimeAgentHomeBridge | None = None,
    ) -> None:
        self._home = home
        self._runtime_bridge = runtime_bridge or RuntimeAgentHomeBridge()

    async def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        home = self._home.using(context.owner_operations)
        link = execution.call.params.get("link")
        old_text = execution.call.params.get("old_text")
        new_text = execution.call.params.get("new_text")
        expected_digest = execution.call.params.get("expected_digest", "")
        if (
            not isinstance(link, str)
            or not link
            or not isinstance(old_text, str)
            or not old_text
            or not isinstance(new_text, str)
            or not isinstance(expected_digest, str)
        ):
            return _failed(
                execution,
                "home.resource.patch parameters are invalid.",
                reason="invalid_parameters",
            )
        try:
            result = await home.patch_resource(
                link,
                old_text=old_text,
                new_text=new_text,
                expected_digest=expected_digest,
            )
        except AgentHomeContractError:
            return _failed(
                execution,
                "Home resource patch request rejected; check the Link and current content.",
                reason="resource_patch_failed",
            )
        except AgentHomeError as exc:
            raise self._runtime_bridge.from_home_error(exc) from exc
        return _mutation_success(execution, result)


class HomeResourceDeleteExecutor(ActionExecutor):
    """Tombstone a progressive resource in the active Home overlay."""

    def __init__(
        self,
        home: HomeService,
        runtime_bridge: RuntimeAgentHomeBridge | None = None,
    ) -> None:
        self._home = home
        self._runtime_bridge = runtime_bridge or RuntimeAgentHomeBridge()

    async def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        home = self._home.using(context.owner_operations)
        link = execution.call.params.get("link")
        expected_digest = execution.call.params.get("expected_digest", "")
        if (
            not isinstance(link, str)
            or not link
            or not isinstance(expected_digest, str)
        ):
            return _failed(
                execution,
                "home.resource.delete parameters are invalid.",
                reason="invalid_parameters",
            )
        try:
            result = await home.delete_resource(
                link,
                expected_digest=expected_digest,
            )
        except AgentHomeContractError:
            return _failed(
                execution,
                "Home resource delete request rejected; check the Link and current content.",
                reason="resource_delete_failed",
            )
        except AgentHomeError as exc:
            raise self._runtime_bridge.from_home_error(exc) from exc
        return _mutation_success(execution, result)


class HomeTopWriteExecutor(ActionExecutor):
    """Create or replace a non-MEMORY top entry in the active overlay."""

    def __init__(
        self,
        home: HomeService,
        runtime_bridge: RuntimeAgentHomeBridge | None = None,
    ) -> None:
        self._home = home
        self._runtime_bridge = runtime_bridge or RuntimeAgentHomeBridge()

    async def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        home = self._home.using(context.owner_operations)
        bus = context.require_signal_bus()
        link = execution.call.params.get("link")
        text = execution.call.params.get("text")
        overwrite = execution.call.params.get("overwrite", False)
        expected_digest = execution.call.params.get("expected_digest", "")
        if not isinstance(link, str) or not link or not isinstance(text, str):
            return _failed(
                execution,
                "home.top.write requires non-empty 'link' and string 'text'.",
                reason="invalid_parameters",
            )
        if not isinstance(overwrite, bool) or not isinstance(expected_digest, str):
            return _failed(
                execution,
                "home.top.write precondition parameters are invalid.",
                reason="invalid_precondition",
            )
        try:
            result = await home.write_top(
                link,
                text,
                overwrite=overwrite,
                expected_digest=expected_digest,
            )
        except AgentHomeContractError:
            return _failed(
                execution,
                "Home top write request rejected; check the Link and current content.",
                reason="top_write_failed",
            )
        except AgentHomeError as exc:
            raise self._runtime_bridge.from_home_error(exc) from exc
        bus.emit(
            Signal(
                name=HOME_CONTEXT_UPDATE,
                source="home.action",
                scope=execution.framework.scope,
                payload={"refresh": True},
            )
        )
        return _mutation_success(execution, result)


class HomeTopPatchExecutor(ActionExecutor):
    """Patch one non-MEMORY top entry in the active overlay."""

    def __init__(
        self,
        home: HomeService,
        runtime_bridge: RuntimeAgentHomeBridge | None = None,
    ) -> None:
        self._home = home
        self._runtime_bridge = runtime_bridge or RuntimeAgentHomeBridge()

    async def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        home = self._home.using(context.owner_operations)
        bus = context.require_signal_bus()
        link = execution.call.params.get("link")
        old_text = execution.call.params.get("old_text")
        new_text = execution.call.params.get("new_text")
        expected_digest = execution.call.params.get("expected_digest", "")
        if (
            not isinstance(link, str)
            or not link
            or not isinstance(old_text, str)
            or not old_text
            or not isinstance(new_text, str)
            or not isinstance(expected_digest, str)
        ):
            return _failed(
                execution,
                "home.top.patch parameters are invalid.",
                reason="invalid_parameters",
            )
        try:
            result = await home.patch_top(
                link,
                old_text=old_text,
                new_text=new_text,
                expected_digest=expected_digest,
            )
        except AgentHomeContractError:
            return _failed(
                execution,
                "Home top patch request rejected; check the Link and current content.",
                reason="top_patch_failed",
            )
        except AgentHomeError as exc:
            raise self._runtime_bridge.from_home_error(exc) from exc
        bus.emit(
            Signal(
                name=HOME_CONTEXT_UPDATE,
                source="home.action",
                scope=execution.framework.scope,
                payload={"refresh": True},
            )
        )
        return _mutation_success(execution, result)


class HomeTopDeleteExecutor(ActionExecutor):
    """Tombstone one non-MEMORY top entry in the active overlay."""

    def __init__(
        self,
        home: HomeService,
        runtime_bridge: RuntimeAgentHomeBridge | None = None,
    ) -> None:
        self._home = home
        self._runtime_bridge = runtime_bridge or RuntimeAgentHomeBridge()

    async def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        home = self._home.using(context.owner_operations)
        bus = context.require_signal_bus()
        link = execution.call.params.get("link")
        expected_digest = execution.call.params.get("expected_digest", "")
        if (
            not isinstance(link, str)
            or not link
            or not isinstance(expected_digest, str)
        ):
            return _failed(
                execution,
                "home.top.delete parameters are invalid.",
                reason="invalid_parameters",
            )
        try:
            result = await home.delete_top(link, expected_digest=expected_digest)
        except AgentHomeContractError:
            return _failed(
                execution,
                "Home top delete request rejected; check the Link and current content.",
                reason="top_delete_failed",
            )
        except AgentHomeError as exc:
            raise self._runtime_bridge.from_home_error(exc) from exc
        bus.emit(
            Signal(
                name=HOME_CONTEXT_UPDATE,
                source="home.action",
                scope=execution.framework.scope,
                payload={"refresh": True},
            )
        )
        return _mutation_success(execution, result)


class HomePromptMountWriteExecutor(ActionExecutor):
    """Create or replace one catalog-defined prompt mount."""

    def __init__(
        self,
        home: HomeService,
        runtime_bridge: RuntimeAgentHomeBridge | None = None,
    ) -> None:
        self._home = home
        self._runtime_bridge = runtime_bridge or RuntimeAgentHomeBridge()

    async def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        home = self._home.using(context.owner_operations)
        link = execution.call.params.get("link")
        text = execution.call.params.get("text")
        overwrite = execution.call.params.get("overwrite", False)
        expected_digest = execution.call.params.get("expected_digest", "")
        if not isinstance(link, str) or not link or not isinstance(text, str):
            return _failed(
                execution,
                "home.prompt_mount.write requires non-empty 'link' and string 'text'.",
                reason="invalid_parameters",
            )
        if not isinstance(overwrite, bool) or not isinstance(expected_digest, str):
            return _failed(
                execution,
                "home.prompt_mount.write precondition parameters are invalid.",
                reason="invalid_precondition",
            )
        try:
            result = await home.write_prompt_mount(
                link,
                text,
                overwrite=overwrite,
                expected_digest=expected_digest,
            )
        except AgentHomeContractError:
            return _failed(
                execution,
                "Home prompt mount write request rejected; check the Link and current content.",
                reason="prompt_mount_write_failed",
            )
        except AgentHomeError as exc:
            raise self._runtime_bridge.from_home_error(exc) from exc
        return _mutation_success(execution, result)


class HomePromptMountPatchExecutor(ActionExecutor):
    """Patch one catalog-defined prompt mount."""

    def __init__(
        self,
        home: HomeService,
        runtime_bridge: RuntimeAgentHomeBridge | None = None,
    ) -> None:
        self._home = home
        self._runtime_bridge = runtime_bridge or RuntimeAgentHomeBridge()

    async def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        home = self._home.using(context.owner_operations)
        link = execution.call.params.get("link")
        old_text = execution.call.params.get("old_text")
        new_text = execution.call.params.get("new_text")
        expected_digest = execution.call.params.get("expected_digest", "")
        if (
            not isinstance(link, str)
            or not link
            or not isinstance(old_text, str)
            or not old_text
            or not isinstance(new_text, str)
            or not isinstance(expected_digest, str)
        ):
            return _failed(
                execution,
                "home.prompt_mount.patch parameters are invalid.",
                reason="invalid_parameters",
            )
        try:
            result = await home.patch_prompt_mount(
                link,
                old_text=old_text,
                new_text=new_text,
                expected_digest=expected_digest,
            )
        except AgentHomeContractError:
            return _failed(
                execution,
                "Home prompt mount patch request rejected; check the Link and current content.",
                reason="prompt_mount_patch_failed",
            )
        except AgentHomeError as exc:
            raise self._runtime_bridge.from_home_error(exc) from exc
        return _mutation_success(execution, result)


def _mutation_success(execution: ActionExecution, result: object) -> ActionResult:
    from ..engine import HomeResourceMutation

    if not isinstance(result, HomeResourceMutation):
        raise AgentHomeInvariantError(
            "Home mutation executor received an invalid result"
        )
    return ActionResult.success(
        call_id=execution.call.call_id,
        invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id,
        action_name=execution.call.action_name,
        sequence=execution.call.sequence,
        domain=execution.framework.domain,
        payload={
            "link": result.link,
            "state": result.state.value,
            "digest": result.digest,
            "baseline_digest": result.baseline_digest,
            "size": result.size,
        },
    )


def _failed(
    execution: ActionExecution,
    model_feedback: str,
    *,
    reason: str,
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
            scope="home.action",
            disposition=ActionFailureDisposition.CHANGE_REQUEST,
            feedback=model_feedback,
        ),
        frame_data=frame_data,
    )
