"""
JSON Schema for Query State context.

Describes the structure of query state context output.
"""


def get_query_state_schema() -> dict:
    """
    Get the JSON schema describing the structure of query state context output.

    Returns:
        Dictionary representing the JSON schema of query state context
    """
    return {
        "type": "object",
        "description": "Query state context containing action records, loop errors, todo_list, milestones, and ongoing actions",
        "properties": {
            "action_record_list": {
                "type": "array",
                "description": "Structured history of all executed actions",
                "items": {
                    "type": "object",
                    "properties": {
                        "turn": {
                            "type": "integer",
                            "description": "Turn number of the action execution",
                        },
                        "action_name": {
                            "type": "string",
                            "description": "Name of the executed action",
                        },
                        "action_target": {
                            "type": "string",
                            "description": "Reason for selecting this action",
                        },
                        "action_input": {
                            "type": "object",
                            "description": "Action parameters as a JSON object",
                        },
                        "action_result": {
                            "type": "object",
                            "description": "Result of the action execution as a JSON object",
                        },
                    },
                    "required": [
                        "turn",
                        "action_name",
                        "action_target",
                        "action_input",
                        "action_result",
                    ],
                },
            },
            "feedback_error_list": {
                "type": "array",
                "description": "Errors encountered during query loop execution that require LLM attention (auto-recovered errors suppressed); recent items are shown in full, older ones are summarized",
                "items": {
                    "type": "object",
                    "properties": {
                        "turn": {
                            "type": "integer",
                            "description": "Turn number where the error occurred",
                        },
                        "step": {
                            "type": "string",
                            "description": "Step name (choose_action, generate_parameters, execute_action, update_state)",
                        },
                        "error_type": {
                            "type": "string",
                            "description": "Type of error (e.g., ActionExecutionError, LLMTransientError, state/KeyError)",
                        },
                        "message": {
                            "type": "string",
                            "description": "Error description",
                        },
                        "timestamp": {
                            "type": "string",
                            "format": "date-time",
                            "description": "Error timestamp (ISO format)",
                        },
                    },
                    "required": ["turn", "step", "error_type", "message", "timestamp"],
                },
            },
            "todo_list": {
                "type": "array",
                "description": "List of todo items with display key",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Exposed key for LLM operations: semantic_key when unique across history, display_key (e.g., verify-1) when the semantic_key has been reused",
                        },
                        "description": {
                            "type": "string",
                            "description": "Todo description",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["PENDING", "DONE", "CANCELLED"],
                            "description": "Todo status: PENDING, DONE, or CANCELLED",
                        },
                        "created_at": {
                            "type": "string",
                            "format": "date-time",
                            "description": "Creation timestamp (ISO format)",
                        },
                        "completed_at": {
                            "type": ["string", "null"],
                            "format": "date-time",
                            "description": "Completion timestamp (ISO format) or null",
                        },
                    },
                    "required": [
                        "key",
                        "description",
                        "status",
                        "created_at",
                        "completed_at",
                    ],
                },
            },
            "milestone_list": {
                "type": "array",
                "description": "List of completed milestone descriptions",
                "items": {"type": "string"},
            },
            "ongoing_action_list": {
                "type": "array",
                "description": "List of currently running ONGOING action executions",
                "items": {
                    "type": "object",
                    "properties": {
                        "execution_id": {
                            "type": "string",
                            "description": "Per-execution id used to stop or correlate the ONGOING action",
                        },
                        "action_name": {
                            "type": "string",
                            "description": "Name of the ONGOING action",
                        },
                        "turn": {
                            "type": "integer",
                            "description": "Turn where the ONGOING execution started",
                        },
                        "status": {
                            "type": "string",
                            "description": "Current runtime status",
                        },
                        "started_at": {
                            "type": ["string", "null"],
                            "format": "date-time",
                            "description": "Start timestamp (ISO format) or null",
                        },
                    },
                    "required": [
                        "execution_id",
                        "action_name",
                        "turn",
                        "status",
                        "started_at",
                    ],
                },
            },
        },
        "required": [
            "action_record_list",
            "feedback_error_list",
            "todo_list",
            "milestone_list",
            "ongoing_action_list",
        ],
    }
