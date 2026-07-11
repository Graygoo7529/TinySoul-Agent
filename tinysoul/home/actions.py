"""Agent Home action executors."""

from __future__ import annotations

from tinysoul.action import (
    ActionEngineBuilder,
    ActionExecution,
    ActionExecutionContext,
    ActionExecutor,
    ActionResult,
    ActionResultStage,
)
from tinysoul.infra.json import JsonObject
from tinysoul.runtime.bridge import RuntimeAgentHomeBridge

from .engine import AgentHomeEngine
from .errors import AgentHomeError, AgentHomeRuntimeCopyRequired


def register_home_actions(
    builder: ActionEngineBuilder,
    *,
    home: AgentHomeEngine,
    runtime_bridge: RuntimeAgentHomeBridge,
) -> ActionEngineBuilder:
    """Register Agent Home action executors on an action builder."""

    return builder.register_executor(
        "home.resource.read",
        HomeResourceReadExecutor(home, runtime_bridge=runtime_bridge),
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
                {"reason": "missing_link"},
            )
        max_chars = execution.call.params.get("max_chars")
        if max_chars is not None and (
            isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars <= 0
        ):
            return self._failed(
                execution,
                "home.resource.read max_chars must be a positive integer.",
                {"reason": "invalid_max_chars"},
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
        except AgentHomeError as exc:
            return self._failed(
                execution,
                f"Agent Home resource read failed: {exc}",
                {"error_type": type(exc).__name__},
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
            },
        )

    def _failed(
        self,
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
