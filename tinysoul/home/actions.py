"""Agent Home action executors."""

from __future__ import annotations

from tinysoul.action import (
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
from tinysoul.runtime.bridge import RuntimeAgentHomeBridge

from .engine import AgentHomeEngine
from .errors import (
    AgentHomeError,
    AgentHomeInvariantError,
    AgentHomeRuntimeCopyRequired,
)
from .search import HomeSearchReranker


def register_home_actions(
    builder: ActionEngineBuilder,
    *,
    home: AgentHomeEngine,
    runtime_bridge: RuntimeAgentHomeBridge,
    search_reranker: HomeSearchReranker | None = None,
) -> ActionEngineBuilder:
    """Register Agent Home action executors on an action builder."""

    builder.register_executor(
        "home.top.search",
        HomeTopSearchExecutor(
            home,
            reranker=search_reranker,
            runtime_bridge=runtime_bridge,
        ),
    )
    builder.register_executor(
        "home.resource.read",
        HomeResourceReadExecutor(home, runtime_bridge=runtime_bridge),
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


class HomeTopSearchExecutor(ActionExecutor):
    """Search bounded effective Home top metadata."""

    def __init__(
        self,
        home: AgentHomeEngine,
        *,
        reranker: HomeSearchReranker | None = None,
        runtime_bridge: RuntimeAgentHomeBridge | None = None,
    ) -> None:
        self._home = home
        self._reranker = reranker
        self._runtime_bridge = runtime_bridge or RuntimeAgentHomeBridge()

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        query = execution.call.params.get("query")
        top_k = execution.call.params.get("top_k")
        if not isinstance(query, str) or not query.strip():
            return _failed(
                execution,
                "home.top.search requires a non-empty 'query' parameter.",
                reason="invalid_query",
            )
        if top_k is not None and (
            isinstance(top_k, bool) or not isinstance(top_k, int)
        ):
            return _failed(
                execution,
                "home.top.search top_k must be an integer.",
                reason="invalid_top_k",
            )
        try:
            result = self._home.search_top(
                query,
                top_k=top_k if isinstance(top_k, int) else None,
                reranker=self._reranker,
                scope=execution.framework.scope,
            )
        except AgentHomeInvariantError as exc:
            raise self._runtime_bridge.from_home_error(exc) from exc
        except AgentHomeError as exc:
            return _failed(
                execution,
                f"Agent Home top search failed: {exc}",
                reason="top_search_failed",
                frame_data={"error_type": type(exc).__name__},
            )
        return ActionResult.success(
            call_id=execution.call.call_id,
            invoke_id=execution.framework.invoke_id,
            batch_id=execution.framework.batch_id,
            action_name=execution.call.action_name,
            sequence=execution.call.sequence,
            domain=execution.framework.domain,
            payload={
                "query": result.query,
                "top_k": result.top_k,
                "candidate_count": result.candidate_count,
                "reranked": result.reranked,
                "items": [item.to_json() for item in result.items],
            },
        )


class HomeResourceReadExecutor(ActionExecutor):
    """Read a bounded Agent Home progressive resource."""

    def __init__(
        self,
        home: AgentHomeEngine,
        runtime_bridge: RuntimeAgentHomeBridge | None = None,
    ) -> None:
        self._home = home
        self._runtime_bridge = runtime_bridge or RuntimeAgentHomeBridge()

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        link = execution.call.params.get("link")
        if not isinstance(link, str) or not link:
            return self._failed(
                execution,
                "home.resource.read requires a non-empty 'link' parameter.",
                reason="missing_link",
            )
        max_chars = execution.call.params.get("max_chars")
        if max_chars is not None and (
            isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars <= 0
        ):
            return self._failed(
                execution,
                "home.resource.read max_chars must be a positive integer.",
                reason="invalid_max_chars",
            )
        try:
            result = self._home.read_resource(
                link,
                max_chars=max_chars if isinstance(max_chars, int) else None,
            )
        except AgentHomeRuntimeCopyRequired as exc:
            raise self._runtime_bridge.runtime_copy_required(
                link=exc.link,
                payload=exc.to_payload(),
            ) from exc
        except AgentHomeInvariantError as exc:
            raise self._runtime_bridge.from_home_error(exc) from exc
        except AgentHomeError as exc:
            return self._failed(
                execution,
                f"Agent Home resource read failed: {exc}",
                reason="resource_read_failed",
                frame_data={"error_type": type(exc).__name__},
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
                "text": result.text,
                "truncated": result.truncated,
                "digest": result.digest,
            },
        )

    def _failed(
        self,
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


class HomeResourceWriteExecutor(ActionExecutor):
    """Create or replace a progressive resource in the active Home overlay."""

    def __init__(
        self,
        home: AgentHomeEngine,
        runtime_bridge: RuntimeAgentHomeBridge | None = None,
    ) -> None:
        self._home = home
        self._runtime_bridge = runtime_bridge or RuntimeAgentHomeBridge()

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
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
            result = self._home.write_resource(
                link,
                text,
                overwrite=overwrite,
                expected_digest=expected_digest,
            )
        except AgentHomeInvariantError as exc:
            raise self._runtime_bridge.from_home_error(exc) from exc
        except AgentHomeError as exc:
            return _failed(
                execution,
                f"Agent Home resource write failed: {exc}",
                reason="resource_write_failed",
                frame_data={"error_type": type(exc).__name__},
            )
        return _mutation_success(execution, result)


class HomeResourcePatchExecutor(ActionExecutor):
    """Apply one deterministic exact replacement to the active Home overlay."""

    def __init__(
        self,
        home: AgentHomeEngine,
        runtime_bridge: RuntimeAgentHomeBridge | None = None,
    ) -> None:
        self._home = home
        self._runtime_bridge = runtime_bridge or RuntimeAgentHomeBridge()

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
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
            result = self._home.patch_resource(
                link,
                old_text=old_text,
                new_text=new_text,
                expected_digest=expected_digest,
            )
        except AgentHomeInvariantError as exc:
            raise self._runtime_bridge.from_home_error(exc) from exc
        except AgentHomeError as exc:
            return _failed(
                execution,
                f"Agent Home resource patch failed: {exc}",
                reason="resource_patch_failed",
                frame_data={"error_type": type(exc).__name__},
            )
        return _mutation_success(execution, result)


class HomeResourceDeleteExecutor(ActionExecutor):
    """Tombstone a progressive resource in the active Home overlay."""

    def __init__(
        self,
        home: AgentHomeEngine,
        runtime_bridge: RuntimeAgentHomeBridge | None = None,
    ) -> None:
        self._home = home
        self._runtime_bridge = runtime_bridge or RuntimeAgentHomeBridge()

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        link = execution.call.params.get("link")
        expected_digest = execution.call.params.get("expected_digest", "")
        if not isinstance(link, str) or not link or not isinstance(expected_digest, str):
            return _failed(
                execution,
                "home.resource.delete parameters are invalid.",
                reason="invalid_parameters",
            )
        try:
            result = self._home.delete_resource(
                link,
                expected_digest=expected_digest,
            )
        except AgentHomeInvariantError as exc:
            raise self._runtime_bridge.from_home_error(exc) from exc
        except AgentHomeError as exc:
            return _failed(
                execution,
                f"Agent Home resource delete failed: {exc}",
                reason="resource_delete_failed",
                frame_data={"error_type": type(exc).__name__},
            )
        return _mutation_success(execution, result)


class HomeTopWriteExecutor(ActionExecutor):
    """Create or replace a non-MEMORY top entry in the active overlay."""

    def __init__(
        self,
        home: AgentHomeEngine,
        runtime_bridge: RuntimeAgentHomeBridge | None = None,
    ) -> None:
        self._home = home
        self._runtime_bridge = runtime_bridge or RuntimeAgentHomeBridge()

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
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
        if (
            not isinstance(overwrite, bool)
            or not isinstance(expected_digest, str)
        ):
            return _failed(
                execution,
                "home.top.write precondition parameters are invalid.",
                reason="invalid_precondition",
            )
        try:
            result = self._home.write_top(
                link,
                text,
                overwrite=overwrite,
                expected_digest=expected_digest,
            )
        except AgentHomeInvariantError as exc:
            raise self._runtime_bridge.from_home_error(exc) from exc
        except AgentHomeError as exc:
            return _failed(
                execution,
                f"Agent Home top write failed: {exc}",
                reason="top_write_failed",
                frame_data={"error_type": type(exc).__name__},
            )
        return _mutation_success(execution, result)


class HomeTopPatchExecutor(ActionExecutor):
    """Patch one non-MEMORY top entry in the active overlay."""

    def __init__(
        self,
        home: AgentHomeEngine,
        runtime_bridge: RuntimeAgentHomeBridge | None = None,
    ) -> None:
        self._home = home
        self._runtime_bridge = runtime_bridge or RuntimeAgentHomeBridge()

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
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
            result = self._home.patch_top(
                link,
                old_text=old_text,
                new_text=new_text,
                expected_digest=expected_digest,
            )
        except AgentHomeInvariantError as exc:
            raise self._runtime_bridge.from_home_error(exc) from exc
        except AgentHomeError as exc:
            return _failed(
                execution,
                f"Agent Home top patch failed: {exc}",
                reason="top_patch_failed",
                frame_data={"error_type": type(exc).__name__},
            )
        return _mutation_success(execution, result)


class HomeTopDeleteExecutor(ActionExecutor):
    """Tombstone one non-MEMORY top entry in the active overlay."""

    def __init__(
        self,
        home: AgentHomeEngine,
        runtime_bridge: RuntimeAgentHomeBridge | None = None,
    ) -> None:
        self._home = home
        self._runtime_bridge = runtime_bridge or RuntimeAgentHomeBridge()

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        link = execution.call.params.get("link")
        expected_digest = execution.call.params.get("expected_digest", "")
        if not isinstance(link, str) or not link or not isinstance(expected_digest, str):
            return _failed(
                execution,
                "home.top.delete parameters are invalid.",
                reason="invalid_parameters",
            )
        try:
            result = self._home.delete_top(link, expected_digest=expected_digest)
        except AgentHomeInvariantError as exc:
            raise self._runtime_bridge.from_home_error(exc) from exc
        except AgentHomeError as exc:
            return _failed(
                execution,
                f"Agent Home top delete failed: {exc}",
                reason="top_delete_failed",
                frame_data={"error_type": type(exc).__name__},
            )
        return _mutation_success(execution, result)


class HomePromptMountWriteExecutor(ActionExecutor):
    """Create or replace one catalog-defined prompt mount."""

    def __init__(
        self,
        home: AgentHomeEngine,
        runtime_bridge: RuntimeAgentHomeBridge | None = None,
    ) -> None:
        self._home = home
        self._runtime_bridge = runtime_bridge or RuntimeAgentHomeBridge()

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
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
            result = self._home.write_prompt_mount(
                link,
                text,
                overwrite=overwrite,
                expected_digest=expected_digest,
            )
        except AgentHomeInvariantError as exc:
            raise self._runtime_bridge.from_home_error(exc) from exc
        except AgentHomeError as exc:
            return _failed(
                execution,
                f"Agent Home prompt mount write failed: {exc}",
                reason="prompt_mount_write_failed",
                frame_data={"error_type": type(exc).__name__},
            )
        return _mutation_success(execution, result)


class HomePromptMountPatchExecutor(ActionExecutor):
    """Patch one catalog-defined prompt mount."""

    def __init__(
        self,
        home: AgentHomeEngine,
        runtime_bridge: RuntimeAgentHomeBridge | None = None,
    ) -> None:
        self._home = home
        self._runtime_bridge = runtime_bridge or RuntimeAgentHomeBridge()

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
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
            result = self._home.patch_prompt_mount(
                link,
                old_text=old_text,
                new_text=new_text,
                expected_digest=expected_digest,
            )
        except AgentHomeInvariantError as exc:
            raise self._runtime_bridge.from_home_error(exc) from exc
        except AgentHomeError as exc:
            return _failed(
                execution,
                f"Agent Home prompt mount patch failed: {exc}",
                reason="prompt_mount_patch_failed",
                frame_data={"error_type": type(exc).__name__},
            )
        return _mutation_success(execution, result)


def _mutation_success(execution: ActionExecution, result: object) -> ActionResult:
    from .engine import HomeResourceMutation

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
