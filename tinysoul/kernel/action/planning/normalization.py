"""Action call and execution input models."""

from __future__ import annotations


from tinysoul.infra.json import JsonObject
from tinysoul.llm.protocol.tools import ToolCallRecord, ToolKind

from ..catalog.catalog import ActionCatalog
from ..execution.hooks import ActionNormalizeHookPipeline, ActionNormalizeInput
from ..result import (
    ActionFailureDisposition,
    ActionLocalFailure,
    ActionResult,
    ActionResultStage,
)


from ..call import ActionCall, ActionNormalization


class ActionCallNormalizer:
    """Normalize Phase2 tool calls into action calls."""

    def __init__(self, hooks: ActionNormalizeHookPipeline | None = None) -> None:
        self._hooks = hooks or ActionNormalizeHookPipeline()

    def normalize(
        self,
        tool_calls: tuple[ToolCallRecord, ...],
        *,
        catalog: ActionCatalog,
    ) -> ActionNormalization:
        calls: list[ActionCall] = []
        results: list[ActionResult] = []
        seen_call_ids: set[str] = set()
        for index, tool_call in enumerate(tool_calls):
            sequence = index + 1
            if tool_call.id in seen_call_ids:
                results.append(
                    _normalize_failure(
                        tool_call,
                        sequence=sequence,
                        feedback=f"Duplicate action tool call id: {tool_call.id}",
                        reason="duplicate_call_id",
                    )
                )
                continue
            seen_call_ids.add(tool_call.id)
            if tool_call.kind is not ToolKind.ACTION:
                results.append(
                    _normalize_failure(
                        tool_call,
                        sequence=sequence,
                        feedback=(
                            "Expected an action tool call, but received a control or "
                            "uncategorized tool call."
                        ),
                        reason="unexpected_tool_kind",
                        frame_data={
                            "tool_kind": (
                                tool_call.kind.value if tool_call.kind else None
                            )
                        },
                    )
                )
                continue
            if not catalog.has_action(tool_call.name):
                results.append(
                    _normalize_failure(
                        tool_call,
                        sequence=sequence,
                        feedback=f"Unknown action tool call: {tool_call.name}",
                        reason="unknown_action",
                    )
                )
                continue
            action = catalog.get_action(tool_call.name)
            hook_result = self._hooks.run(
                ActionNormalizeInput(
                    tool_call=tool_call,
                    action=action,
                    sequence=sequence,
                )
            )
            if hook_result is not None:
                results.append(hook_result)
                continue
            calls.append(
                ActionCall(
                    call_id=tool_call.id,
                    action_name=tool_call.name,
                    params=tool_call.arguments,
                    sequence=sequence,
                )
            )
        return ActionNormalization(
            calls=tuple(calls),
            results=tuple(results),
        )


def _normalize_failure(
    tool_call: ToolCallRecord,
    *,
    sequence: int,
    feedback: str,
    reason: str,
    frame_data: JsonObject | None = None,
) -> ActionResult:
    return ActionResult.failed(
        call_id=tool_call.id,
        action_name=tool_call.name,
        stage=ActionResultStage.NORMALIZE,
        sequence=sequence,
        failure=ActionLocalFailure(
            reason=reason,
            scope="action.normalize",
            disposition=ActionFailureDisposition.CHANGE_REQUEST,
            feedback=feedback,
        ),
        frame_data=frame_data,
    )
