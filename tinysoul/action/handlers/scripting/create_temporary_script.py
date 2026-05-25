"""
Create Temporary Script Action - creates a Python script file in the workspace
with LLM-generated code.

This action is the companion to ``register_temporary_script``:
1. LLM calls ``create_temporary_script`` to write a ``.py`` file into the workspace
2. LLM calls ``register_temporary_script`` to register that file as a runnable
   SCRIPT action for the current query loop.
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

ACTION_SPEC_CREATE_TEMPORARY_SCRIPT = {
    "name": "create_temporary_script",
    "description": "Create a Python script file in the workspace with LLM-generated code. Use this when the LLM needs to write custom logic (e.g. data analysis, text processing) as a reusable script before registering it as a temporary action. This action only writes the script file; it does not register or execute it.",
    "cluster": {
        "type": "NATIVE",
        "domain": "SCRIPTING",
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
                "need to create a custom Python script in the workspace",
                "need to generate code that will later be registered as a temporary action",
            ],
        },
        "preconditions": [
            "target_access must not already exist in the workspace",
            "file path must be within workspace_location boundary",
            "must not conflict with existing target_access",
        ],
        "postconditions": {
            "logical_state_effects": [
                "Adds a new ResourceItem to workspace.resources",
                "Initializes resource_desc and change_log",
                "Script is ready to be registered with register_temporary_script",
                "Script has not been executed yet",
            ],
            "physical_environment_effects": [
                "Creates a new .py file on disk at the specified relative path",
            ],
        },
    },
    "detail": {
        "parameter_schema": {
            "type": "object",
            "properties": {
                "target_access": {
                    "type": "string",
                    "description": "Relative path for the new script file (should end with .py, e.g. 'scripts/my_analyzer.py')",
                },
                "instruction": {
                    "type": "string",
                    "description": "Concise natural-language direction (1-3 sentences) describing what the script should do. Do NOT paste the full script source here; the action will generate the code internally.",
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
                "target_access": "scripts/analyze_csv.py",
                "instruction": "Write a script that reads a CSV file and prints summary statistics",
                "reference_accesses": [
                    "data/sample.csv",
                ],
            },
        ],
        "edge_case_handling": [
            "File already exists: reject with error, suggest edit_temporary_script instead",
            "Parent directory does not exist: auto-create directories",
            "Path traversal outside workspace: reject with error",
            "Missing reference resource: reject with error",
            "Instruction too long or contains full script source: the instruction should be a brief direction, not the full code; suggest using reference_accesses for source material",
            "Creation does not execute the script: call register_temporary_script next, then call the registered action in a later turn",
        ],
    },
}

ACTION_JSON_CREATE_TEMPORARY_SCRIPT = json.dumps(ACTION_SPEC_CREATE_TEMPORARY_SCRIPT, ensure_ascii=False, indent=2)


def _build_script_prompt(builder, params, workspace):
    """Build prompt for creating a new Python script file."""
    instruction = params.get("instruction", "")
    refs_data = workspace.load_reference_data(params.get("reference_accesses", []))

    return builder.build(
        task_guide=(
            "Write a complete, self-contained Python script. "
            "The script MUST define a top-level function:\n\n"
            "    def _tinysoul_script(action_input: dict, context: dict) -> Any:\n"
            "        ...\n\n"
            "This function is the entry point when the script is executed as a SCRIPT action.\n\n"
            "IMPORTANT: The script runs in a sandboxed environment.\n"
            "- The current working directory is the workspace root. Relative paths resolve against the workspace.\n"
            "- `__file__` is defined and points to the script file's absolute path.\n"
            "- You CAN read/write files using `open()` or `pathlib`. Parent directories are created automatically when using `open()` in write mode.\n"
            "- You CANNOT access the network or use system calls (subprocess is blocked).\n"
            "- Do NOT import `os` or `sys`. Import only from allowed standard library modules (json, re, math, collections, csv, pathlib, etc.).\n\n"
            "Design your parameter schema so that the caller passes file paths or data via action_input, "
            "and the script reads the files itself. Do NOT expect action_input['reference_files'] to contain file contents.\n\n"
            "RETURN VALUE CONTRACT (action_result lightweightness):\n"
            "- BOTH the return value of _tinysoul_script AND anything printed to stdout are captured as the action_result.\n"
            "- For SMALL outputs (numbers, booleans, short strings ≤ 200 chars), return or print them directly.\n"
            "- For LARGE outputs (long text, big tables, full reports), WRITE them to a workspace file "
            "  (preferably a markdown file under reports/ or docs/) and return ONLY the file path and a brief summary.\n"
            "  Example (good): return {'output_file': 'reports/analysis.md', 'summary': 'Top products ranked by revenue'}\n"
            "  Example (bad):  return {'result': '<entire 5000-line text pasted here>'} or print a 5000-line report\n"
            "- Large action_results bloat action_record_list and waste token budget in future turns.\n"
            "- Always prefer writing files to the workspace over returning or printing large payloads."
        ),
        input_spec=InputSpec(
            description="Instruction for what the script should do, plus optional reference files.",
            data={
                "instruction": instruction,
                "reference_files": refs_data,
            },
        ),
        output_constraint=OutputConstraint(
            description="Provide a JSON object with exactly three fields: "
            '"content": the complete Python script source code (raw code without markdown fences), '
            '"resource_desc": {"summary": "a concise neutral summary of the script (1-2 sentences)"}, '
            '"change_log_summary": "a brief semantic description of what was created"\n'
            "DO NOT include markdown code blocks or any other text outside the JSON object. Return raw JSON only.",
        ),
    )


def _apply_script_result(params, generated, workspace, context_provider):
    """Apply LLM-generated script content to create a new file."""
    target_access = params.get("target_access", "")
    if not target_access:
        raise ActionExecutionError("target_access is required")

    target_path = workspace.resolve_access(target_access)
    if target_path.exists():
        raise ActionExecutionError(
            f"File '{target_access}' already exists. Use edit_temporary_script instead."
        )

    content = generated.get("content", "")
    desc_data = generated.get("resource_desc", {})
    change_summary = generated.get(
        "change_log_summary", "Created script via create_temporary_script"
    )

    target_path.parent.mkdir(parents=True, exist_ok=True)
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(content)

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
                operation=ChangeOperation.CREATED,
                summary=change_summary,
            )
        ],
    )
    workspace.add_resource(resource)
    return {"message": f"Created script file '{target_access}'", "file_path": target_access}


class CreateTemporaryScriptAction(ActionBase):
    """Action to create a Python script file with LLM-generated code."""

    action_name = "create_temporary_script"
    ACTION_JSON = ACTION_JSON_CREATE_TEMPORARY_SCRIPT

    def __init__(self):
        super().__init__()
        self._executor = OneStepAIExecutor(
            build_prompt=_build_script_prompt,
            apply_result=_apply_script_result,
        )


def register_to(registry):
    """Register createtemporaryscript action to the given registry."""
    from tinysoul.action.framework.registry import ActionRegistry

    if isinstance(registry, ActionRegistry):
        registry.register_action_class(CreateTemporaryScriptAction)
