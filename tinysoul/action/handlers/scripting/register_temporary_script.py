"""
Register Temporary Script Action - registers a new SCRIPT action
from a workspace Python file.

This action is LLM-dependent (llm_dependency=REQUIRED):
1. LLM provides new_action_name and script_path
2. Framework reads the script content
3. Framework calls LLM to generate the complete ACTION_JSON
4. Framework validates and registers the new handler
"""

import json
from typing import Any

from tinysoul.action.framework.executor import ActionExecutor
from tinysoul.action.framework.handler import ActionBase, make_handler
from tinysoul.prompt.action import build_llm_action_system, get_register_script_system
from tinysoul.action.executors.llm._common import run_llm_task
from tinysoul.action.executors.script import TemporaryScriptExecutor
from tinysoul.action.framework.registry import ActionRegistry
from tinysoul.action.framework.run_config import RunConfig
from tinysoul.action.framework.validation import validate_action_metadata
from tinysoul.context.protocols import ContextProvider
from tinysoul.trap import ActionExecutionError, ActionInputError
from tinysoul.infra.sandbox import validate_ast
from tinysoul.llm.tasks import InputSpec, LLMPrompt, OutputConstraint, PromptBuilder

ACTION_SPEC_REGISTER_TEMPORARY_SCRIPT = {
    "name": "register_temporary_script",
    "description": "Register a workspace Python script as a new temporary SCRIPT action. Use this after create_temporary_script or edit_temporary_script. This action only registers the script; it does not execute it. Call the newly registered action in a later turn to run the script.",
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
                "need to create a custom action for the current query loop",
                "have a Python script file ready in the workspace",
            ],
        },
        "preconditions": [
            "script_path must point to an existing .py file in the workspace",
            "script must define `_tinysoul_script(action_input, context)`",
            "new_action_name must not already be registered",
        ],
        "postconditions": {
            "logical_state_effects": [
                "New action is registered and available in subsequent turns",
            ],
            "physical_environment_effects": [],
        },
    },
    "detail": {
        "parameter_schema": {
            "type": "object",
            "properties": {
                "new_action_name": {
                    "type": "string",
                    "description": "Unique name for the new action",
                },
                "script_path": {
                    "type": "string",
                    "description": "Relative path to the Python script file in the workspace (e.g. 'scripts/my_analyzer.py')",
                },
            },
            "required": [
                "new_action_name",
                "script_path",
            ],
        },
        "examples": [
            {
                "new_action_name": "analyze_csv",
                "script_path": "scripts/analyze.py",
            },
        ],
        "edge_case_handling": [
            "Script file not found: reject with error",
            "Script fails AST validation: reject with error",
            "Action name already registered: reject with error",
            "LLM fails to generate valid action_json: reject with error",
            "If validation reports a missing ACTION_JSON field, retry registration with the same script_path and ensure the generated metadata includes the required field",
        ],
    },
}

ACTION_JSON_REGISTER_TEMPORARY_SCRIPT = json.dumps(ACTION_SPEC_REGISTER_TEMPORARY_SCRIPT, ensure_ascii=False, indent=2)


def _build_register_prompt(
    builder: PromptBuilder,
    params: dict[str, Any],
    workspace: Any,
    script_source: str,
    action_schema: dict[str, Any],
) -> LLMPrompt:
    """Build prompt for LLM to generate ACTION_JSON from script content."""
    new_action_name = params["new_action_name"]
    script_path = params["script_path"]

    return builder.build(
        task_guide=(
            "Generate a complete ACTION_JSON for the given Python script.\n\n"
            "FIXED FIELD VALUES (the framework will override these regardless of what you write):\n"
            f'- name = "{new_action_name}"\n'
            '- cluster.type = "SCRIPT"\n'
            '- profile.action_intention = "EXECUTION"\n'
            '- profile.action_environment_effect = "MODIFYING"\n'
            '- profile.action_mode = "SINGLE_RUN"\n'
            '- profile.llm_dependency = "NONE"\n\n'
            "You should still include these fields in your output for completeness, but use the values above.\n\n"
            "FIELDS YOU MUST INFER FROM THE SCRIPT (use action_structure_reference for schema details):\n"
            '- description: what the script does (concise but complete)\n'
            '- cluster.domain: "SCRIPTING" or a relevant domain\n'
            '- contract.applicability: mode="CONDITIONAL", conditions=list of when to use this action\n'
            '- contract.preconditions: list of requirements before execution\n'
            '- contract.postconditions: logical_state_effects and physical_environment_effects\n'
            '- detail.parameter_schema: JSON schema for action_input. Must match what '
            '  `_tinysoul_script(action_input, context)` expects.\n'
            '  - Analyze the function signature and body to infer required/optional fields.\n'
            '  - If the script reads files, expose file paths as string parameters.\n'
            '  - If the script accepts configuration, expose those as typed parameters.\n'
            '  - Do NOT include "reference_files" in parameter_schema; the script reads files itself.\n'
            '- detail.examples: 1-2 realistic example input objects\n'
            '- detail.edge_case_handling: list of common errors and how to handle them\n\n'
            "Return ONLY a valid JSON object (the complete ACTION_JSON)."
        ),
        input_spec=InputSpec(
            description="Script content, registration parameters, and ACTION_JSON schema reference.",
            data={
                "new_action_name": new_action_name,
                "script_path": script_path,
                "script_source": script_source,
                "action_structure_reference": action_schema,
            },
        ),
        output_constraint=OutputConstraint(
            description="A complete ACTION_JSON object as valid JSON. "
            "It MUST include top-level keys: name, description, cluster, profile, contract, detail. "
            "The detail object MUST include: parameter_schema, examples, edge_case_handling. "
            "DO NOT include markdown code blocks or any other text outside the JSON object. Return raw JSON only."
        ),
    )


def _validation_retry_hint(message: str) -> str:
    required_top_level = "name, description, cluster, profile, contract, detail"
    detail_fields = "parameter_schema, examples, edge_case_handling"
    return (
        f"{message}. Retry register_temporary_script with the same script_path and "
        f"generate a complete ACTION_JSON. Required top-level keys: {required_top_level}. "
        f"Required detail keys: {detail_fields}."
    )


class RegisterTemporaryScriptExecutor(ActionExecutor):
    """
    Executor that validates parameters, reads the script,
    calls LLM to generate ACTION_JSON, and registers the new handler.
    """

    def execute(
        self,
        action_input: dict,
        context_provider: ContextProvider | None,
        run_config: RunConfig,
    ) -> dict:
        if context_provider is None:
            raise ActionExecutionError(
                "register_temporary_script requires a ContextProvider"
            )
        run_config.raise_if_terminated()

        workspace = context_provider.workspace
        if workspace is None:
            raise ActionExecutionError(
                "register_temporary_script requires workspace in context"
            )

        # 1. Extract parameters
        params = action_input
        new_action_name = params.get("new_action_name")
        script_path = params.get("script_path")

        if not new_action_name:
            raise ActionInputError("'new_action_name' is required")
        if not script_path:
            raise ActionInputError("'script_path' is required")

        # 2. Verify script file exists and pass AST validation
        resolved = workspace.resolve_access(script_path)
        if not resolved.exists():
            raise ActionExecutionError(f"Script file not found: {script_path}")

        source = resolved.read_text(encoding="utf-8")
        validate_ast(source)

        # 3. Get QueryAction from context and check for duplicates
        query_action = context_provider.query_action

        # Allow re-registration of temporary scripts after edits
        if query_action.is_action_available(new_action_name):
            query_action.unregister_action(new_action_name)

        # 4. Call LLM to generate ACTION_JSON
        from tinysoul.action.framework.schema import get_action_schema
        builder = PromptBuilder(context_provider)
        prompt = _build_register_prompt(
            builder, params, workspace, source, get_action_schema()
        )

        client = None
        if context_provider is not None:
            client = getattr(context_provider, "client", None)

        try:
            generated = run_llm_task(
                prompt=prompt,
                system=build_llm_action_system(
                    context_provider,
                    action_system=get_register_script_system(),
                ),
                client=client,
                run_config=run_config,
            )
        except Exception as e:
            raise ActionExecutionError(
                f"LLM failed to generate action_json: {e}", action_input=action_input
            ) from e

        # 5. Validate generated action_json
        if not isinstance(generated, dict):
            raise ActionInputError(
                f"LLM returned non-dict action_json: {type(generated).__name__}"
            )

        if generated.get("name") != new_action_name:
            raise ActionInputError(
                f"action_json name mismatch: expected '{new_action_name}', "
                f"got '{generated.get('name')}'"
            )

        # Ensure cluster.type is SCRIPT and effect reflects write capability
        cluster = generated.get("cluster", {})
        if cluster.get("type") != "SCRIPT":
            generated["cluster"] = {**cluster, "type": "SCRIPT"}

        profile = generated.get("profile", {})
        if profile.get("action_environment_effect") == "READ_ONLY":
            profile["action_environment_effect"] = "MODIFYING"
            generated["profile"] = profile

        # Full structural validation before registration
        action_json = json.dumps(generated, ensure_ascii=False)
        try:
            validate_action_metadata(action_json)
        except ActionExecutionError as exc:
            raise ActionInputError(
                "Generated ACTION_JSON failed structural validation: "
                f"{_validation_retry_hint(str(exc))}",
                action_input=action_input,
            ) from exc

        # 6. Register through QueryAction
        def factory():
            executor = TemporaryScriptExecutor(script_path)
            return make_handler(
                name=new_action_name,
                action_json=action_json,
                executor=executor,
            )

        query_action.register_action(new_action_name, action_json, factory)
        run_config.raise_if_terminated()

        return {
            "message": f"Action '{new_action_name}' registered successfully. The script has NOT been executed yet — call the registered action in a subsequent turn to run it.",
            "script_path": str(script_path),
            "registered_action": new_action_name,
        }


class RegisterTemporaryScriptAction(ActionBase):
    """Action to register a new temporary script from a workspace file."""

    action_name = "register_temporary_script"
    ACTION_JSON = ACTION_JSON_REGISTER_TEMPORARY_SCRIPT

    def __init__(self):
        super().__init__()
        self._executor = RegisterTemporaryScriptExecutor()


def register_to(registry: ActionRegistry) -> None:
    """Register the register_temporary_script action to the given registry."""
    registry.register(
        "register_temporary_script",
        ACTION_JSON_REGISTER_TEMPORARY_SCRIPT,
        lambda: RegisterTemporaryScriptAction(),
    )
