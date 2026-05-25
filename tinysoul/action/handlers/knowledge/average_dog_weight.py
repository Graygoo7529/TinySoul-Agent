"""
Average Dog Weight Action - ACTION_JSON definition and execution for getting dog breed weights.
"""
import json

from tinysoul.action.framework.executor import ActionExecutor
from tinysoul.action.framework.handler import ActionBase
from tinysoul.action.framework.run_config import RunConfig
from tinysoul.context.protocols import ContextProvider
from tinysoul.trap import ActionExecutionError, ActionInputError
from tinysoul.action.tools import average_dog_weight as average_dog_weight_tool

ACTION_SPEC_AVERAGE_DOG_WEIGHT = {
    "name": "average_dog_weight",
    "description": "Returns average weight of a dog when given the breed",
    "cluster": {
        "type": "NATIVE",
        "domain": "KNOWLEDGE",
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
                "need to know dog breed weight AVERAGE",
                "animal information query",
            ],
        },
        "preconditions": [
            "Input must be a dog breed name",
        ],
        "postconditions": {
            "logical_state_effects": [
                "Returns the average weight description for the breed",
            ],
            "physical_environment_effects": [],
        },
    },
    "detail": {
        "parameter_schema": {
            "type": "object",
            "properties": {
                "breed": {
                    "type": "string",
                    "description": "Dog breed name (e.g., 'Border Collie', 'Scottish Terrier')",
                },
            },
            "required": [
                "breed",
            ],
        },
        "examples": [
            {
                "breed": "Border Collie",
            },
            {
                "breed": "Scottish Terrier",
            },
        ],
        "edge_case_handling": [
            "Handle unknown breed names: feedback to user",
            "Handle empty input: feedback to user",
            "Handle case sensitivity",
        ],
    },
}

ACTION_JSON_AVERAGE_DOG_WEIGHT = json.dumps(ACTION_SPEC_AVERAGE_DOG_WEIGHT, ensure_ascii=False, indent=2)


class AverageDogWeightExecutor(ActionExecutor):
    """Executor for dog breed weight queries."""

    def execute(
        self,
        action_input: dict,
        context_provider: ContextProvider | None,
        run_config: RunConfig,
    ) -> dict:
        run_config.raise_if_terminated()
        breed = action_input.get("breed", "")
        if not breed:
            raise ActionInputError("No breed provided", action_input=action_input)

        try:
            result = average_dog_weight_tool(breed)
        except Exception as e:
            raise ActionExecutionError(
                f"Query failed: {e}", action_input=action_input
            ) from e

        return {"average_weight": result, "breed": breed}


class AverageDogWeightAction(ActionBase):
    """Action to query average weight of a dog breed."""

    action_name = "average_dog_weight"
    ACTION_JSON = ACTION_JSON_AVERAGE_DOG_WEIGHT
    _executor = AverageDogWeightExecutor()


def register_to(registry):
    """Register averagedogweight action to the given registry."""
    from tinysoul.action.framework.registry import ActionRegistry

    if isinstance(registry, ActionRegistry):
        registry.register_action_class(AverageDogWeightAction)
