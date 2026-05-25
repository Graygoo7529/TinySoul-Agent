"""
Read File Action - reads a text file in the workspace and updates its resource_desc via LLM.

Supports readable text types: MARKDOWN, TXT, JSON, CSV, PY, and UNKNOWN.
Rejects binary types that require external parsers: PDF, DOCX.
"""
import json

from tinysoul.action.framework.handler import ActionBase
from tinysoul.action.executors.llm import OneStepAIExecutor
from tinysoul.infra.config import settings
from tinysoul.trap import ActionExecutionError
from tinysoul.llm.tasks import InputSpec, OutputConstraint
from tinysoul.context.workspace import (
    BINARY_TYPES,
    TEXT_READABLE_TYPES,
    ChangeLogItem,
    ChangeOperation,
    ResourceDesc,
    ResourceType,
)

ACTION_SPEC_READ_FILE = {
    "name": "read_file",
    "description": "Read a text file in the workspace and update its resource_desc. File content is summarized into workspace metadata; it is NOT returned in action output. Supports markdown, text, JSON, CSV, Python scripts, and other readable text files.",
    "cluster": {
        "type": "NATIVE",
        "domain": "WORKSPACE",
    },
    "profile": {
        "action_intention": "EXTERNAL_PROBING",
        "action_environment_effect": "READ_ONLY",
        "action_mode": "SINGLE_RUN",
        "llm_dependency": "REQUIRED",
    },
    "contract": {
        "applicability": {
            "mode": "CONDITIONAL",
            "conditions": [
                "need to understand content of a workspace text file",
                "need to update resource_desc for an existing resource",
            ],
        },
        "preconditions": [
            "target_access must point to an existing readable text file in workspace",
            "file must be within workspace_location boundary",
            "file must be a valid UTF-8 text file (not binary)",
        ],
        "postconditions": {
            "logical_state_effects": [
                "Updates resource_desc.summary for the target resource",
                "Appends READ entry to change_log",
            ],
            "physical_environment_effects": [],
        },
    },
    "detail": {
        "parameter_schema": {
            "type": "object",
            "properties": {
                "target_access": {
                    "type": "string",
                    "description": "Relative path of the text file in workspace",
                },
            },
            "required": [
                "target_access",
            ],
        },
        "examples": [
            {
                "target_access": "docs/design_notes.md",
            },
            {
                "target_access": "data/numbers.csv",
            },
        ],
        "edge_case_handling": [
            "File not found: return error without modifying workspace",
            "Binary file (PDF/DOCX): reject with error, suggest using a custom script if analysis is needed",
            "Non-UTF-8 file: reject with error",
            "Path traversal outside workspace: reject with error",
        ],
    },
}

ACTION_JSON_READ_FILE = json.dumps(ACTION_SPEC_READ_FILE, ensure_ascii=False, indent=2)


def _build_read_prompt(builder, params, workspace):
    """Build prompt for reading and summarizing a text file."""
    target_access = params.get("target_access", "")

    target_path = workspace.resolve_access(target_access)
    if not target_path.exists():
        raise ActionExecutionError(f"File '{target_access}' not found")

    resource = workspace.find_resource(target_access)
    if resource is None:
        raise ActionExecutionError(f"Resource '{target_access}' not found in workspace")

    if resource.resource_type in BINARY_TYPES:
        raise ActionExecutionError(
            f"Resource '{target_access}' is a {resource.resource_type.value} file. "
            f"Binary files require external parsers and cannot be read directly. "
            f"Consider creating a temporary script to process it."
        )

    # Attempt UTF-8 read; catch decode errors for non-text files.
    try:
        with open(target_path, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError as exc:
        raise ActionExecutionError(
            f"File '{target_access}' is not a valid UTF-8 text file"
        ) from exc

    return builder.build(
        task_guide="Summarize a text document and explain its relevance to the user's task.",
        input_spec=InputSpec(
            description="The text document content to summarize.",
            data={
                "target_file": target_access,
                "document": content[:settings.content_truncate],
            },
        ),
        output_constraint=OutputConstraint(
            description='Provide a JSON object with exactly two fields:\n'
            '- "resource_desc": {"summary": "A concise neutral summary (1-2 sentences)"}\n'
            '- "relevance": "How this document relates to the current query/target (1 sentence)"\n'
            "DO NOT include markdown code blocks or any other text outside the JSON object. Return raw JSON only.",
        ),
    )


def _apply_read_result(params, generated, workspace, context_provider):
    """Apply LLM-generated resource_desc to an existing resource."""
    target_access = params.get("target_access", "")
    if not target_access:
        raise ActionExecutionError("target_access is required")

    resource = workspace.find_resource(target_access)
    if resource is None:
        raise ActionExecutionError(f"Resource '{target_access}' not found in workspace")

    desc_data = generated.get("resource_desc", {})
    relevance = generated.get("relevance", "")

    resource.resource_desc = ResourceDesc(
        summary=desc_data.get("summary", ""),
    )
    resource.change_log.append(
        ChangeLogItem(
            turn=context_provider.current_turn,
            operation=ChangeOperation.READ,
            summary="Read and summarized file via read_file",
        )
    )

    return {
        "message": f"Read file '{target_access}'",
        "file_path": target_access,
        "relevance": relevance,
    }


class ReadFileAction(ActionBase):
    """Action to read a text file and update its resource_desc via LLM."""

    action_name = "read_file"
    ACTION_JSON = ACTION_JSON_READ_FILE

    def __init__(self):
        super().__init__()
        self._executor = OneStepAIExecutor(
            build_prompt=_build_read_prompt,
            apply_result=_apply_read_result,
        )


def register_to(registry):
    """Register read_file action to the given registry."""
    from tinysoul.action.framework.registry import ActionRegistry

    if isinstance(registry, ActionRegistry):
        registry.register_action_class(ReadFileAction)
