from __future__ import annotations

from tinysoul.action.core.feedback import ActionFeedbackRenderer
from tinysoul.action.core.result import ActionResult, ActionResultStage
from tinysoul.llm.messages import JsonPart
from tinysoul.llm.tools import ToolResultStatus


def test_feedback_renderer_creates_success_tool_result_message() -> None:
    result = ActionResult.success(
        call_id="call_1",
        invoke_id="invoke_1",
        batch_id="batch_1",
        action_name="workspace.scan",
        sequence=1,
        domain="workspace",
        payload={"ok": True},
        model_feedback="Scan completed.",
    )

    message = ActionFeedbackRenderer().to_tool_result_message(result)

    assert message.call_id == "call_1"
    assert message.tool_name == "workspace.scan"
    assert message.status is ToolResultStatus.OK
    assert isinstance(message.parts[0], JsonPart)
    assert message.parts[0].value["status"] == "success"
    assert message.parts[0].value["payload"] == {"ok": True}


def test_feedback_renderer_creates_error_tool_result_message() -> None:
    result = ActionResult.failed(
        call_id="call_1",
        action_name="workspace.scan",
        stage=ActionResultStage.NORMALIZE,
        sequence=1,
        model_feedback="Invalid arguments.",
    )

    message = ActionFeedbackRenderer().to_tool_result_message(result)

    assert message.call_id == "call_1"
    assert message.status is ToolResultStatus.ERROR
    assert isinstance(message.parts[0], JsonPart)
    assert message.parts[0].value["stage"] == "normalize"
