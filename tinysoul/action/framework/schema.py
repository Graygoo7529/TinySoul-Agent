"""
JSON Schema for Action definitions.

Describes the structure used when creating or registering a new action.
"""

from typing import Any


def get_action_schema() -> dict[str, Any]:
    """
    Get the JSON schema for creating a new action.

    Returns:
        Dictionary representing the schema for action creation
    """
    return {
        "type": "object",
        "description": "Schema for creating/registering a new action",
        "properties": {
            "name": {
                "type": "string",
                "description": "Unique name of the action",
            },
            "description": {
                "type": "string",
                "description": "Description of what the action does",
            },
            "cluster": {
                "type": "object",
                "description": "Action cluster configuration",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["NATIVE", "CLI", "SCRIPT"],
                        "description": "Execution mechanism type of the action",
                    },
                    "domain": {
                        "type": "string",
                        "description": "Business domain of the action (e.g., MATH, WORKSPACE, KNOWLEDGE)",
                    },
                },
            },
            "profile": {
                "type": "object",
                "description": "Action profile configuration",
                "properties": {
                    "action_intention": {
                        "type": "string",
                        "enum": ["EXTERNAL_PROBING", "INTERNAL_REASONING", "EXECUTION"],
                        "description": "Intention of the action",
                    },
                    "action_environment_effect": {
                        "type": "string",
                        "enum": ["READ_ONLY", "ADDITIVE", "MODIFYING", "DESTRUCTIVE"],
                        "description": "Effect on the environment",
                    },
                    "action_mode": {
                        "type": "string",
                        "enum": ["SINGLE_RUN", "ONGOING"],
                        "description": "Execution mode",
                    },
                    "llm_dependency": {
                        "type": "string",
                        "enum": ["NONE", "OPTIONAL", "REQUIRED"],
                        "description": "LLM dependency level",
                    },
                },
            },
            "contract": {
                "type": "object",
                "description": "Action contract",
                "properties": {
                    "applicability": {
                        "type": "object",
                        "properties": {
                            "mode": {
                                "type": "string",
                                "enum": ["ALWAYS_CONSIDER", "CONDITIONAL"],
                                "description": "Applicability mode",
                            },
                            "conditions": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                    },
                    "preconditions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Required state dependencies",
                    },
                    "postconditions": {
                        "type": "object",
                        "properties": {
                            "logical_state_effects": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "physical_environment_effects": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                    },
                },
            },
            "detail": {
                "type": "object",
                "description": "Action detail information",
                "properties": {
                    "parameter_schema": {
                        "type": "object",
                        "description": "JSON schema for action input parameters",
                    },
                    "examples": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "List of example input objects",
                    },
                    "edge_case_handling": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of edge case handlers",
                    },
                },
            },
        },
        "required": ["name"],
    }
