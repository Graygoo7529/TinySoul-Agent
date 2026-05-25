"""Stop Ongoing Action - requests termination of an ONGOING execution."""

from __future__ import annotations

import json

from tinysoul.action.framework.executor import ActionExecutor
from tinysoul.action.framework.handler import ActionBase
from tinysoul.action.framework.run_config import RunConfig, TerminationReason
from tinysoul.context.protocols import ContextProvider
from tinysoul.trap import ActionExecutionError, ActionInputError


ACTION_SPEC_STOP_ONGOING_ACTION = {
    "name": "stop_ongoing_action",
    "description": "Request termination of a running ONGOING action by execution_id",
    "cluster": {
        "type": "NATIVE",
        "domain": "MONITOR",
    },
    "profile": {
        "action_intention": "EXECUTION",
        "action_environment_effect": "READ_ONLY",
        "action_mode": "SINGLE_RUN",
        "llm_dependency": "NONE",
    },
    "contract": {
        "applicability": {
            "mode": "CONDITIONAL",
            "conditions": [
                "need to stop an item listed in ongoing_action_list",
            ],
        },
        "preconditions": [
            "execution_id must identify a running ONGOING action execution",
        ],
        "postconditions": {
            "logical_state_effects": [
                "Requests termination for the matching ONGOING execution",
                "The ONGOING execution emits ONGOING_COMPLETED when it stops",
            ],
            "physical_environment_effects": [],
        },
    },
    "detail": {
        "parameter_schema": {
            "type": "object",
            "properties": {
                "execution_id": {
                    "type": "string",
                    "description": "The execution_id from ongoing_action_list",
                },
                "reason": {
                    "type": "string",
                    "enum": [
                        "user_cancel",
                        "shutdown",
                    ],
                    "description": "Termination reason (default: user_cancel)",
                },
            },
            "required": [
                "execution_id",
            ],
        },
        "examples": [
            {
                "execution_id": "abc123def456",
                "reason": "user_cancel",
            },
        ],
        "edge_case_handling": [
            "Unknown execution_id: return an action error",
            "Already completed execution: return an action error",
        ],
    },
}

ACTION_JSON_STOP_ONGOING_ACTION = json.dumps(
    ACTION_SPEC_STOP_ONGOING_ACTION,
    ensure_ascii=False,
    indent=2,
)


class StopOngoingActionExecutor(ActionExecutor):
    """Executor that requests termination for a running ONGOING execution."""

    def execute(
        self,
        action_input: dict,
        context_provider: ContextProvider | None,
        run_config: RunConfig,
    ) -> dict:
        if context_provider is None:
            raise ActionExecutionError("stop_ongoing_action requires a ContextProvider")
        run_config.raise_if_terminated()

        execution_id = action_input.get("execution_id", "")
        if not execution_id:
            raise ActionInputError(
                "'execution_id' is required",
                action_input=action_input,
            )

        raw_reason = action_input.get("reason", TerminationReason.USER_CANCEL.value)
        try:
            reason = TerminationReason(raw_reason)
        except ValueError as exc:
            raise ActionInputError(
                f"Unsupported termination reason: {raw_reason}",
                action_input=action_input,
            ) from exc

        requester = getattr(context_provider, "request_ongoing_termination", None)
        if not callable(requester):
            raise ActionExecutionError(
                "ContextProvider does not support ongoing termination"
            )

        if not requester(execution_id, reason):
            raise ActionExecutionError(
                f"ONGOING execution not found or already completed: {execution_id}",
                action_input=action_input,
            )

        return {
            "status": "termination_requested",
            "execution_id": execution_id,
            "reason": reason.value,
        }


class StopOngoingAction(ActionBase):
    """Action to stop a running ONGOING execution by execution_id."""

    action_name = "stop_ongoing_action"
    ACTION_JSON = ACTION_JSON_STOP_ONGOING_ACTION
    _executor = StopOngoingActionExecutor()


def register_to(registry):
    """Register stop_ongoing_action to the given registry."""
    from tinysoul.action.framework.registry import ActionRegistry

    if isinstance(registry, ActionRegistry):
        registry.register_action_class(StopOngoingAction)

