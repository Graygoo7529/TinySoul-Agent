from __future__ import annotations

import pytest

from tinysoul.action.core.errors import ActionInvariantError
from tinysoul.action.core.rendering import ActionResultRenderer
from tinysoul.action.core.result import (
    ActionFailureDisposition,
    ActionLocalFailure,
    ActionPhaseResult,
    ActionPhaseResultStage,
    ActionResult,
    ActionResultEnvelope,
    ActionResultStage,
)
from tinysoul.llm.messages import JsonPart
from tinysoul.llm.tools import ToolResultStatus
from tinysoul.runtime import CyclePhase


def _failure() -> ActionLocalFailure:
    return ActionLocalFailure(
        reason="invalid_arguments",
        scope="action.normalize",
        disposition=ActionFailureDisposition.CHANGE_REQUEST,
        feedback="Invalid arguments.",
    )


def test_result_renderer_creates_success_tool_result_message() -> None:
    result = ActionResult.success(
        call_id="call_1",
        invoke_id="invoke_1",
        batch_id="batch_1",
        action_name="workspace.scan",
        sequence=1,
        domain="workspace",
        payload={"ok": True},
    )

    rendered = ActionResultRenderer().render_tool_result(result)
    message = rendered.visible_message

    assert message is rendered.canonical_message
    assert message.call_id == "call_1"
    assert message.tool_name == "workspace.scan"
    assert message.status is ToolResultStatus.OK
    assert isinstance(message.parts[0], JsonPart)
    assert message.parts[0].value == {
        "action": "workspace.scan",
        "status": "success",
        "stage": "execute",
        "payload": {"ok": True},
    }


def test_result_renderer_creates_error_tool_result_message() -> None:
    result = ActionResult.failed(
        call_id="call_1",
        action_name="workspace.scan",
        stage=ActionResultStage.NORMALIZE,
        sequence=1,
        failure=_failure(),
    )

    message = ActionResultRenderer().render_tool_result(result).visible_message

    assert message.call_id == "call_1"
    assert message.status is ToolResultStatus.ERROR
    assert isinstance(message.parts[0], JsonPart)
    assert message.parts[0].value["failure"] == _failure().to_json()


def test_result_renderer_keeps_hook_diagnostics_out_of_model_feedback() -> None:
    result = ActionResult.failed(
        call_id="call_hook",
        action_name="workspace.scan",
        stage=ActionResultStage.HOOK,
        sequence=1,
        failure=_failure(),
        payload={"blocked_resource": "resource_1"},
        frame_data={"hook": "policy", "policy_revision": 3},
    )
    renderer = ActionResultRenderer()

    model_payload = renderer.render_model_payload(result)
    trace_payload = renderer.render_trace_payload(result)

    assert model_payload["payload"] == {"blocked_resource": "resource_1"}
    assert model_payload["failure"] == _failure().to_json()
    assert "frame_data" not in model_payload
    assert trace_payload["frame_data"] == {
        "hook": "policy",
        "policy_revision": 3,
    }


def test_result_renderer_renders_phase_result_payloads() -> None:
    result = ActionPhaseResult.failed(
        phase=CyclePhase.PHASE2,
        stage=ActionPhaseResultStage.NORMALIZE,
        failure=_failure(),
        frame_data={"reason": "missing_action_call"},
    )

    renderer = ActionResultRenderer()
    model_payload = renderer.render_phase_model_payload(result)
    trace_payload = renderer.render_phase_trace_payload(result)

    assert model_payload["phase"] == "phase2"
    assert model_payload["failure"] == _failure().to_json()
    assert trace_payload["frame_data"] == {"reason": "missing_action_call"}


def test_canonical_result_parser_rejects_unknown_legacy_fields() -> None:
    with pytest.raises(ActionInvariantError, match="unknown fields"):
        ActionResultEnvelope.from_json(
            {
                "action": "workspace.scan",
                "status": "success",
                "stage": "execute",
                "feedback": "legacy",
            }
        )
