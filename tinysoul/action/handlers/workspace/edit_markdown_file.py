"""
Edit Markdown File Action - edits markdown file with LLM-generated new content.
"""
import json

from tinysoul.action.framework.handler import ActionBase
from tinysoul.action.executors.llm import OneStepAIExecutor
from tinysoul.infra.config import settings
from tinysoul.trap import ActionExecutionError
from tinysoul.llm.tasks import InputSpec, OutputConstraint
from tinysoul.context.workspace import (
    ChangeLogItem,
    ChangeOperation,
    ResourceDesc,
)

ACTION_SPEC_EDIT_MARKDOWN_FILE = {
    "name": "edit_markdown_file",
    "description": "Edit a markdown file in workspace with LLM-generated new content. File content is generated internally by the action; do NOT embed content in parameters.",
    "cluster": {
        "type": "NATIVE",
        "domain": "WORKSPACE",
    },
    "profile": {
        "action_intention": "EXECUTION",
        "action_environment_effect": "MODIFYING",
        "action_mode": "SINGLE_RUN",
        "llm_dependency": "REQUIRED",
    },
    "contract": {
        "applicability": {
            "mode": "CONDITIONAL",
            "conditions": [
                "need to modify an existing markdown file in workspace",
            ],
        },
        "preconditions": [
            "target_access must point to an existing markdown file in workspace",
            "file must be within workspace_location boundary",
        ],
        "postconditions": {
            "logical_state_effects": [
                "Updates resource_desc if content changed significantly",
                "Appends EDITED entry to change_log",
            ],
            "physical_environment_effects": [
                "Overwrites the file on disk with new content",
            ],
        },
    },
    "detail": {
        "parameter_schema": {
            "type": "object",
            "properties": {
                "target_access": {
                    "type": "string",
                    "description": "Relative path of the file to edit",
                },
                "instruction": {
                    "type": "string",
                    "description": "Concise natural-language direction (1-3 sentences) for how to modify the file. Do NOT paste the full replacement text here; the action will generate the new content internally based on the current file content.",
                },
                "reference_accesses": {
                    "type": "array",
                    "items": {
                        "type": "string",
                    },
                    "description": "List of workspace resource_access paths to attach as reference context. Use this to point to existing files instead of embedding their contents in the instruction.",
                },
            },
            "required": [
                "target_access",
                "instruction",
            ],
        },
        "examples": [
            {
                "target_access": "docs/design_notes.md",
                "instruction": "Add workspace section based on current state and action schema",
                "reference_accesses": [
                    "docs/action-state-queryloop.md",
                ],
            },
        ],
        "edge_case_handling": [
            "File not found: reject with error",
            "Non-markdown file: reject with error",
            "Path traversal outside workspace: reject with error",
            "Missing reference resource: reject with error",
            "Instruction too long or contains full replacement text: the instruction should be a brief direction, not the full text; suggest using reference_accesses for source material",
        ],
    },
}

ACTION_JSON_EDIT_MARKDOWN_FILE = json.dumps(ACTION_SPEC_EDIT_MARKDOWN_FILE, ensure_ascii=False, indent=2)


def _build_edit_prompt(builder, params, workspace):
    """Build prompt for editing an existing markdown file."""
    target_access = params.get("target_access", "")
    instruction = params.get("instruction", "")
    reference_accesses = params.get("reference_accesses", [])

    target_path = workspace.resolve_access(target_access)
    if not target_path.exists():
        raise ActionExecutionError(f"File '{target_access}' not found")

    with open(target_path, "r", encoding="utf-8") as f:
        current_content = f.read()
    refs_data = workspace.load_reference_data(reference_accesses)

    return builder.build(
        task_guide="Provide the COMPLETE new content for the file after applying the instruction above.",
        input_spec=InputSpec(
            description="Target file current content, instruction, and optional reference files.",
            data={
                "target_file": target_access,
                "current_content": current_content[:settings.content_truncate],
                "instruction": instruction,
                "reference_files": refs_data,
            },
        ),
        output_constraint=OutputConstraint(
            description="Provide a JSON object with exactly three fields: "
            '"content": the complete new file content (raw markdown without code fences), '
            '"resource_desc": {"summary": "a concise neutral summary (1-2 sentences)"}, '
            '"change_log_summary": "a brief semantic description of what was edited"\n'
            "DO NOT include markdown code blocks or any other text outside the JSON object. Return raw JSON only.",
        ),
    )


def _apply_edit_result(params, generated, workspace, context_provider):
    """Apply LLM-generated content to edit an existing file."""
    target_access = params.get("target_access", "")
    if not target_access:
        raise ActionExecutionError("target_access is required")

    target_path = workspace.resolve_access(target_access)
    if not target_path.exists():
        raise ActionExecutionError(f"File '{target_access}' not found")

    content = generated.get("content", "")
    desc_data = generated.get("resource_desc", {})
    change_summary = generated.get(
        "change_log_summary", "Edited file via edit_markdown_file"
    )

    with open(target_path, "w", encoding="utf-8") as f:
        f.write(content)

    resource = workspace.find_resource(target_access)
    if resource is None:
        raise ActionExecutionError(f"Resource '{target_access}' not found in workspace")

    resource.resource_desc = ResourceDesc(summary=desc_data.get("summary", ""))
    resource.change_log.append(
        ChangeLogItem(
            turn=context_provider.current_turn,
            operation=ChangeOperation.EDITED,
            summary=change_summary,
        )
    )
    return {
        "message": f"Edited markdown file '{target_access}'",
        "file_path": target_access,
    }


class EditMarkdownFileAction(ActionBase):
    """Action to edit a markdown file with LLM-generated new content."""

    action_name = "edit_markdown_file"
    ACTION_JSON = ACTION_JSON_EDIT_MARKDOWN_FILE

    def __init__(self):
        super().__init__()
        self._executor = OneStepAIExecutor(
            build_prompt=_build_edit_prompt,
            apply_result=_apply_edit_result,
        )


def register_to(registry):
    """Register editmarkdownfile action to the given registry."""
    from tinysoul.action.framework.registry import ActionRegistry

    if isinstance(registry, ActionRegistry):
        registry.register_action_class(EditMarkdownFileAction)
