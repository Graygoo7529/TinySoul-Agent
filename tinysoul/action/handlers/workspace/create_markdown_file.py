"""
Create Markdown File Action - creates markdown file with LLM-generated content.
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
    ResourceItem,
    ResourceType,
)

ACTION_SPEC_CREATE_MARKDOWN_FILE = {
    "name": "create_markdown_file",
    "description": "Create a markdown file in workspace with LLM-generated content. File content is generated internally by the action; do NOT embed content in parameters.",
    "cluster": {
        "type": "NATIVE",
        "domain": "WORKSPACE",
    },
    "profile": {
        "action_intention": "EXECUTION",
        "action_environment_effect": "ADDITIVE",
        "action_mode": "SINGLE_RUN",
        "llm_dependency": "REQUIRED",
    },
    "contract": {
        "applicability": {
            "mode": "CONDITIONAL",
            "conditions": [
                "need to create a new markdown document in workspace",
            ],
        },
        "preconditions": [
            "target_access must not already exist in workspace",
            "file path must be within workspace_location boundary",
            "must not conflict with existing target_access",
        ],
        "postconditions": {
            "logical_state_effects": [
                "Adds a new ResourceItem to workspace.resources",
                "Initializes resource_desc and change_log",
            ],
            "physical_environment_effects": [
                "Creates a new file on disk at the specified relative path",
            ],
        },
    },
    "detail": {
        "parameter_schema": {
            "type": "object",
            "properties": {
                "target_access": {
                    "type": "string",
                    "description": "Relative path for the new file",
                },
                "instruction": {
                    "type": "string",
                    "description": "Concise natural-language direction (1-3 sentences) for what the file should contain. Do NOT paste the full intended content here; the action will generate the content internally.",
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
                "target_access": "notes/new_feature.md",
                "instruction": "Write a design doc for the new feature based on existing docs",
                "reference_accesses": [
                    "docs/existing_arch.md",
                ],
            },
        ],
        "edge_case_handling": [
            "File already exists: reject with error, suggest edit_markdown_file instead",
            "Parent directory does not exist: auto-create directories",
            "Path traversal outside workspace: reject with error",
            "Missing reference resource: reject with error",
            "Instruction too long or contains full document content: the instruction should be a brief direction, not the full text; suggest breaking into multiple files or using reference_accesses",
        ],
    },
}

ACTION_JSON_CREATE_MARKDOWN_FILE = json.dumps(ACTION_SPEC_CREATE_MARKDOWN_FILE, ensure_ascii=False, indent=2)


def _build_create_prompt(builder, params, workspace):
    """Build prompt for creating a new markdown file."""
    instruction = params.get("instruction", "")
    refs_data = workspace.load_reference_data(params.get("reference_accesses", []))

    return builder.build(
        task_guide="Write the complete content for a new file.",
        input_spec=InputSpec(
            description="Instruction for the new file content, plus optional reference files.",
            data={
                "instruction": instruction,
                "reference_files": refs_data,
            },
        ),
        output_constraint=OutputConstraint(
            description="Provide a JSON object with exactly three fields: "
            '"content": the complete file content (raw markdown without code fences), '
            '"resource_desc": {"summary": "a concise neutral summary (1-2 sentences)"}, '
            '"change_log_summary": "a brief semantic description of what was created"\n'
            "DO NOT include markdown code blocks or any other text outside the JSON object. Return raw JSON only.",
        ),
    )


def _apply_create_result(params, generated, workspace, context_provider):
    """Apply LLM-generated content to create a new file."""
    target_access = params.get("target_access", "")
    if not target_access:
        raise ActionExecutionError("target_access is required")

    target_path = workspace.resolve_access(target_access)
    if target_path.exists():
        raise ActionExecutionError(
            f"File '{target_access}' already exists. Use edit_markdown_file instead."
        )

    content = generated.get("content", "")
    desc_data = generated.get("resource_desc", {})
    change_summary = generated.get(
        "change_log_summary", "Created file via create_markdown_file"
    )

    target_path.parent.mkdir(parents=True, exist_ok=True)
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(content)

    resource = ResourceItem(
        resource_name=target_path.name,
        resource_type=ResourceType.MARKDOWN,
        resource_access=target_access,
        resource_desc=ResourceDesc(summary=desc_data.get("summary", "")),
        change_log=[
            ChangeLogItem(
                turn=context_provider.current_turn,
                operation=ChangeOperation.CREATED,
                summary=change_summary,
            )
        ],
    )
    workspace.add_resource(resource)
    return {
        "message": f"Created markdown file '{target_access}'",
        "file_path": target_access,
    }


class CreateMarkdownFileAction(ActionBase):
    """Action to create a markdown file with LLM-generated content."""

    action_name = "create_markdown_file"
    ACTION_JSON = ACTION_JSON_CREATE_MARKDOWN_FILE

    def __init__(self):
        super().__init__()
        self._executor = OneStepAIExecutor(
            build_prompt=_build_create_prompt,
            apply_result=_apply_create_result,
        )


def register_to(registry):
    """Register createmarkdownfile action to the given registry."""
    from tinysoul.action.framework.registry import ActionRegistry

    if isinstance(registry, ActionRegistry):
        registry.register_action_class(CreateMarkdownFileAction)
