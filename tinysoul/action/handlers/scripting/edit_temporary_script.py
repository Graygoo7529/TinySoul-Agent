"""
Edit Temporary Script Action - modifies an existing Python script file
in the workspace with LLM-generated changes.

This is the companion to ``create_temporary_script``:
- Use ``create_temporary_script`` to write a new script
- Use ``edit_temporary_script`` to fix or extend an existing script
- Use ``register_temporary_script`` to register the (updated) script as an Action
"""
import json

from tinysoul.action.framework.handler import ActionBase
from tinysoul.action.executors.llm import OneStepAIExecutor
from tinysoul.trap import ActionExecutionError
from tinysoul.llm.tasks import InputSpec, OutputConstraint
from tinysoul.context.workspace import (
    ChangeLogItem,
    ChangeOperation,
    ResourceDesc,
    ResourceItem,
    ResourceType,
)

ACTION_SPEC_EDIT_TEMPORARY_SCRIPT = {
    "name": "edit_temporary_script",
    "description": "Edit an existing Python script file in the workspace. Use this when a previously created script needs bug fixes, feature additions, or other modifications before re-registering it as a temporary action.",
    "cluster": {
        "type": "NATIVE",
        "domain": "SCRIPTING",
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
                "need to modify an existing Python script in the workspace",
                "a previously created script has bugs or needs new features",
            ],
        },
        "preconditions": [
            "target_access must point to an existing .py file in the workspace",
            "file path must be within workspace_location boundary",
        ],
        "postconditions": {
            "logical_state_effects": [
                "Updates resource_desc if content changed significantly",
                "Appends EDITED entry to change_log",
            ],
            "physical_environment_effects": [
                "Overwrites the script file on disk with new content",
            ],
        },
    },
    "detail": {
        "parameter_schema": {
            "type": "object",
            "properties": {
                "target_access": {
                    "type": "string",
                    "description": "Relative path of the script file to edit",
                },
                "instruction": {
                    "type": "string",
                    "description": "Concise natural-language direction (1-3 sentences) describing how to modify the script. Do NOT paste the full replacement code here; the action will generate the updated script internally based on the current file content.",
                },
                "reference_accesses": {
                    "type": "array",
                    "items": {
                        "type": "string",
                    },
                    "description": "List of workspace resource_access paths to attach as reference context. Use this to point to existing files instead of embedding their contents in the instruction.",
                },
                "associated_action_name": {
                    "type": "string",
                    "description": "Optional: the registered action name for this script, so the current action_json can be shown for reference",
                },
            },
            "required": [
                "target_access",
                "instruction",
            ],
        },
        "examples": [
            {
                "target_access": "scripts/analyze_csv.py",
                "instruction": "Fix the bug where empty columns cause a division by zero",
                "reference_accesses": [],
                "associated_action_name": "analyze_csv",
            },
        ],
        "edge_case_handling": [
            "File not found: reject with error",
            "Non-Python file: reject with error",
            "Path traversal outside workspace: reject with error",
            "Missing reference resource: reject with error",
            "Instruction too long or contains full replacement code: the instruction should be a brief direction, not the full code; suggest using reference_accesses for source material",
        ],
    },
}

ACTION_JSON_EDIT_TEMPORARY_SCRIPT = json.dumps(ACTION_SPEC_EDIT_TEMPORARY_SCRIPT, ensure_ascii=False, indent=2)


def _build_edit_prompt(builder, params, workspace):
    """Build prompt for editing an existing Python script file."""
    target_access = params.get("target_access", "")
    instruction = params.get("instruction", "")
    reference_accesses = params.get("reference_accesses", [])
    associated_action_name = params.get("associated_action_name")

    target_path = workspace.resolve_access(target_access)
    current_content = ""
    if target_path.exists():
        try:
            current_content = target_path.read_text(encoding="utf-8")
        except Exception:
            pass

    refs_data = workspace.load_reference_data(reference_accesses)

    input_data: dict = {
        "target_access": target_access,
        "current_script_content": current_content,
        "instruction": instruction,
        "reference_files": refs_data,
    }

    # If an associated action name is provided, try to inject its action_json
    # via a registry lookup. Since build_prompt doesn't have registry access,
    # we check if the caller pre-injected it through params.
    current_action_json = params.get("_injected_action_json")
    if current_action_json:
        input_data["current_action_json"] = current_action_json

    return builder.build(
        task_guide=(
            "You are editing an existing Python script. "
            "The script MUST keep the top-level entry point function:\n\n"
            "    def _tinysoul_script(action_input: dict, context: dict) -> Any:\n"
            "        ...\n\n"
            "IMPORTANT: The script runs in a sandboxed environment.\n"
            "- The current working directory is the workspace root. Relative paths resolve against the workspace.\n"
            "- `__file__` is defined and points to the script file's absolute path.\n"
            "- You CAN read/write files using `open()` or `pathlib`. Parent directories are created automatically when using `open()` in write mode.\n"
            "- You CANNOT access the network or use system calls (subprocess is blocked).\n"
            "- Do NOT import `os` or `sys`. Import only from allowed standard library modules (json, re, math, collections, csv, pathlib, etc.).\n\n"
            "Provide the COMPLETE updated script source code, not a diff or patch.\n\n"
            "RETURN VALUE CONTRACT (action_result lightweightness):\n"
            "- The return value of _tinysoul_script becomes the action_result stored in action_record_list.\n"
            "- For SMALL outputs (numbers, booleans, short strings ≤ 200 chars), return them directly.\n"
            "- For LARGE outputs (long text, big tables, full reports), WRITE them to a workspace file "
            "  and return ONLY the file path and a brief summary.\n"
            "  Example (good): return {'output_file': 'results/report.csv', 'row_count': 150, 'summary': 'Top products ranked by revenue'}\n"
            "  Example (bad):  return {'result': '<entire 5000-line text pasted here>'}\n"
            "- Large action_results bloat action_record_list and waste token budget in future turns.\n"
            "- Always prefer writing files to the workspace over returning large payloads."
        ),
        input_spec=InputSpec(
            description="Current script content plus modification instruction and optional reference files.",
            data=input_data,
        ),
        output_constraint=OutputConstraint(
            description="Provide a JSON object with exactly three fields: "
            '"content": the complete updated Python script source code (raw code without markdown fences), '
            '"resource_desc": {"summary": "a concise neutral summary of the updated script (1-2 sentences)"}, '
            '"change_log_summary": "a brief semantic description of what was modified"\n'
            "DO NOT include markdown code blocks or any other text outside the JSON object. Return raw JSON only.",
        ),
    )


def _apply_edit_result(params, generated, workspace, context_provider):
    """Apply LLM-generated edited script content to overwrite an existing file."""
    target_access = params.get("target_access", "")
    if not target_access:
        raise ActionExecutionError("target_access is required")

    target_path = workspace.resolve_access(target_access)
    if not target_path.exists():
        raise ActionExecutionError(f"Script file '{target_access}' not found")

    # Reject non-.py files
    if not target_access.endswith(".py"):
        raise ActionExecutionError(
            f"Target '{target_access}' is not a Python script file"
        )

    content = generated.get("content", "")
    desc_data = generated.get("resource_desc", {})
    change_summary = generated.get(
        "change_log_summary", "Edited script via edit_temporary_script"
    )

    with open(target_path, "w", encoding="utf-8") as f:
        f.write(content)

    # Update workspace resource desc and change_log
    resource = workspace.find_resource(target_access)
    if resource is not None:
        resource.resource_desc.summary = desc_data.get(
            "summary", resource.resource_desc.summary
        )
        resource.change_log.append(
            ChangeLogItem(
                turn=context_provider.current_turn,
                operation=ChangeOperation.EDITED,
                summary=change_summary,
            )
        )
    else:
        desc = ResourceDesc(
            summary=desc_data.get("summary", ""),
        )
        resource = ResourceItem(
            resource_name=target_path.name,
            resource_type=ResourceType.PY,
            resource_access=target_access,
            resource_desc=desc,
            change_log=[
                ChangeLogItem(
                    turn=context_provider.current_turn,
                    operation=ChangeOperation.EDITED,
                    summary=change_summary,
                )
            ],
        )
        workspace.add_resource(resource)

    return {"message": f"Edited script file '{target_access}'", "file_path": target_access}


class EditTemporaryScriptAction(ActionBase):
    """Action to edit an existing Python script file with LLM-generated changes."""

    action_name = "edit_temporary_script"
    ACTION_JSON = ACTION_JSON_EDIT_TEMPORARY_SCRIPT

    def __init__(self, registry=None):
        super().__init__()
        self._registry = registry
        self._executor = OneStepAIExecutor(
            build_prompt=_build_edit_prompt,
            apply_result=_apply_edit_result,
        )

    def execute(
        self,
        action_input: dict,
        context_provider,
        run_config,
    ):
        """Override to inject current action_json when associated_action_name is provided."""
        enriched_input = dict(action_input)
        associated = enriched_input.get("associated_action_name")
        if (
            associated
            and self._registry is not None
            and self._registry.is_registered(associated)
        ):
            enriched_input["_injected_action_json"] = (
                self._registry.get_action_json(associated)
            )
        return super().execute(enriched_input, context_provider, run_config)


def register_to(registry):
    """Register edit_temporary_script action to the given registry."""
    from tinysoul.action.framework.registry import ActionRegistry

    if isinstance(registry, ActionRegistry):
        registry.register(
            "edit_temporary_script",
            ACTION_JSON_EDIT_TEMPORARY_SCRIPT,
            lambda: EditTemporaryScriptAction(registry),
        )
