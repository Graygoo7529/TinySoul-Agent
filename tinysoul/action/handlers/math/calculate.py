"""
Calculate Action - ACTION_JSON definition and execution for mathematical calculations.
"""
import json

from tinysoul.action.framework.executor import ActionExecutor
from tinysoul.action.framework.handler import ActionBase
from tinysoul.action.framework.run_config import RunConfig
from tinysoul.context.protocols import ContextProvider
from tinysoul.trap import ActionExecutionError, ActionInputError
from tinysoul.action.tools import calculate as calculate_tool

ACTION_SPEC_CALCULATE = {
    "name": "calculate",
    "description": "Run a calculation and returns the number - uses Python so be sure to use floating point syntax if necessary",
    "cluster": {
        "type": "NATIVE",
        "domain": "MATH",
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
                "mathematical calculation needed",
                "arithmetic operation",
            ],
        },
        "preconditions": [
            "Input must be a valid Python mathematical expression",
        ],
        "postconditions": {
            "logical_state_effects": [
                "Returns the numerical result of the calculation",
            ],
            "physical_environment_effects": [],
        },
    },
    "detail": {
        "parameter_schema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Mathematical expression to evaluate (e.g., '4 * 7 / 3')",
                },
            },
            "required": [
                "expression",
            ],
        },
        "examples": [
            {
                "expression": "4 * 7 / 3",
            },
            {
                "expression": "10 + 20",
            },
        ],
        "edge_case_handling": [
            "Handle syntax errors in expression",
            "Handle division by zero",
            "Handle invalid input types",
        ],
    },
}

ACTION_JSON_CALCULATE = json.dumps(ACTION_SPEC_CALCULATE, ensure_ascii=False, indent=2)


class CalculateExecutor(ActionExecutor):
    """Executor for mathematical expression evaluation."""

    def execute(
        self,
        action_input: dict,
        context_provider: ContextProvider | None,
        run_config: RunConfig,
    ) -> dict:
        run_config.raise_if_terminated()
        expression = action_input.get("expression", "")
        if not expression:
            raise ActionInputError("No expression provided", action_input=action_input)

        try:
            result = calculate_tool(expression)
        except Exception as e:
            raise ActionExecutionError(
                f"Calculation failed: {e}", action_input=action_input
            ) from e

        return {"value": result, "expression": expression}


class CalculateAction(ActionBase):
    """Action to evaluate a mathematical expression."""

    action_name = "calculate"
    ACTION_JSON = ACTION_JSON_CALCULATE
    _executor = CalculateExecutor()


def register_to(registry):
    """Register calculate action to the given registry."""
    from tinysoul.action.framework.registry import ActionRegistry

    if isinstance(registry, ActionRegistry):
        registry.register_action_class(CalculateAction)
