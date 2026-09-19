"""Loop phase execution units."""

from __future__ import annotations


from tinysoul.kernel.context import ControlResult
from tinysoul.infra.json import JsonObject
from tinysoul.llm.protocol.requests import CallSettings, TaskCancellation
from tinysoul.llm.protocol.responses import AnswerFormat, TaskResult
from tinysoul.llm.protocol.tools import ToolScope, ToolSelection, ToolSpec, ToolUse

from ..interaction.cancellation import TurnCancellation
from ..errors import LoopContractError


def _merge_tool_scopes(
    *scopes: ToolScope,
    forced_name: str | None = None,
) -> ToolScope:
    tools: list[ToolSpec] = []
    names: set[str] = set()
    for scope in scopes:
        for tool in scope.visible_tools():
            if tool.name in names:
                raise LoopContractError(f"Duplicate tool in merged scope: {tool.name}")
            tools.append(tool)
            names.add(tool.name)
    allowed_names = tuple(tool.name for tool in tools)
    return ToolScope(
        tools=tuple(tools),
        selection=ToolSelection(
            allowed_names=allowed_names,
            forced_name=forced_name,
        ),
    )


def _required_tool_settings() -> CallSettings:
    return CallSettings(answer_format=AnswerFormat.NONE, tool_use=ToolUse.REQUIRED)


def _turn_task_cancellation(
    cancellation: TurnCancellation | None,
) -> TaskCancellation | None:
    if cancellation is None:
        return None
    return TaskCancellation(
        cancelled=cancellation.requested,
        remaining_seconds=lambda: None,
        reason=lambda: "turn_cancelled",
    )


def _task_result_feedback(result: TaskResult) -> str:
    if result.failure is None or not result.failure.model_feedback:
        return "LLM task output did not satisfy the phase protocol."
    return result.failure.model_feedback


def _control_result_payload(result: ControlResult) -> JsonObject:
    return {
        "call_id": result.call_id,
        "tool_name": result.tool_name,
        "status": result.status.value,
        "stage": result.stage.value,
        "feedback": result.model_feedback,
        "frame_data": result.frame_data,
    }
