"""Model-visible text owned by kernel.action.

Consumers listed below decide visibility, role, data and failure semantics.
"""

# Tool description. Used by kernel/action/planning/scope.py:build.
SELECT_DOMAINS_DESCRIPTION = (
    "Select action domains for the next action-parameter generation phase."
)


# Task instruction or output constraint. Used by kernel/action/builtins/core/actions.py:answer_prompt.
ANSWER_EXPECTED_OUTPUT = (
    "# Expected Output\nReturn a JSON object with a string field 'text'. If source refs"
    " are used, include a 'references' array of source ref strings."
)

# Task instruction or output constraint. Used by kernel/action/tasks.py:selection_input.
SELECTION_CONTEXT_GUIDE = (
    "Use the current Context as reference for the requested candidate selection."
)

# Model instruction or presentation. Used by kernel/action/planning/scope.py:render.
AVAILABLE_DOMAINS_HEADING = "Available action domains:"

# Model instruction or presentation. Used by kernel/action/planning/scope.py:normalize_selection.
NO_USABLE_DOMAINS = "select_action_domains.domains contained no usable domains."

# Model instruction or presentation. Used by kernel/action/planning/scope.py:normalize_selection.
DOMAIN_NAMES_REQUIRED = "select_action_domains.domains must contain non-empty strings."

# Model instruction or presentation. Used by kernel/action/planning/scope.py:_description.
USE_WHEN_HEADING = "Use when: "

# Model instruction or presentation. Used by kernel/action/planning/scope.py:_description.
AVOID_WHEN_HEADING = "Avoid when: "

# Model instruction or presentation. Used by kernel/action/planning/scope.py:_description.
EFFECTS_HEADING = "Effects: "

# Model instruction or presentation. Used by kernel/action/planning/scope.py:_description.
EXAMPLES_HEADING = "Examples: "

# Model instruction or presentation. Used by kernel/action/tasks.py:with_action_skills.
DOMAIN_SKILL_HEADING = "# Domain Skill\n"

# Model instruction or presentation. Used by kernel/action/tasks.py:with_action_skills.
ACTION_SKILL_HEADING = "# Action Skill\n"

# Model instruction or presentation. Used by kernel/action/builtins/core/actions.py:context_task_prompt.
TASK_GUIDE_HEADING = "Task Guide"

# Model instruction or presentation. Used by kernel/action/builtins/core/actions.py:context_task_prompt.
EXPECTED_OUTPUT_HEADING = "Expected Output"

# Model instruction or presentation. Used by kernel/action/builtins/core/actions.py:answer_prompt.
ANSWER_GUIDE_HEADING = "Answer Guide"

# Model instruction or presentation. Used by kernel/action/builtins/core/actions.py:context_task_prompt.
TASK_INPUT_HEADING = "Task Input"

# Model instruction or presentation. Used by kernel/action/builtins/core/actions.py:answer_prompt.
ANSWER_INPUT_HEADING = "Answer Input"


# Model task text or feedback. Used by kernel/action/planning/scope.py:_domain_selection_feedback.
def unknown_domain(*, domain: str) -> str:
    return f"Unknown action domain: {domain}"


# Model task text or feedback. Used by kernel/action/planning/scope.py:_domain_selection_feedback.
def empty_domain(*, domain: str) -> str:
    return f"Action domain has no available actions: {domain}"


# Model task text or feedback. Used by kernel/action/planning/scope.py:render.
def domain_selection_hint(*, selection_hint: str) -> str:
    return f"  Selection hint: {selection_hint}"


# Model task text or feedback. Used by kernel/action/tasks.py:failure.
def task_failed(*, subject: str) -> str:
    return f"{subject} failed."


# Model task text or feedback. Used by kernel/action/builtins/core/actions.py:_parse_block_item.
def task_block(*, heading: str, text: str) -> str:
    return f"# {heading}\n{text}"


# Model tool parameter description. Used by kernel/action/planning/scope.py:build.
DOMAIN_NAMES_DESCRIPTION = "Action domain names to expose in Phase2."

# Model tool parameter description. Used by kernel/action/planning/scope.py:build.
DOMAIN_INTENT_DESCRIPTION = "Brief reason for the selected action domains."
# Local model feedback. Used by kernel/action/builtins/core/actions.py:execute.
INVALID_QUESTION = (
    "Provide one question with unique option IDs, labels and a positive optional "
    "timeout. Do not combine conflicting explicit choices and question blocks."
)

# Local model feedback. Used by kernel/action/builtins/core/actions.py:execute.
INVALID_WAIT = (
    "Choose a positive timeout or an explicit event kind and optional identity."
)


# Local model feedback. Used by kernel/action/builtins/core/actions.py:_parse_blocks.
def required_prompt_blocks(*, key: str) -> str:
    return f"Model task requires non-empty '{key}'."


# Local model feedback. Used by kernel/action/builtins/core/actions.py:_parse_blocks.
def prompt_blocks_must_be_list(*, key: str) -> str:
    return f"Model task '{key}' must be a list."


# Local model feedback. Used by kernel/action/builtins/core/actions.py:_parse_block_item.
def prompt_blocks_must_be_objects(*, key: str) -> str:
    return f"Model task '{key}' items must be objects."


# Local model feedback. Used by kernel/action/builtins/core/actions.py:_parse_block_item.
def prompt_block_text_required(*, key: str) -> str:
    return f"Model task '{key}' items require non-empty text."


# Local model feedback. Used by kernel/action/builtins/core/actions.py:_parse_block_item.
def prompt_block_label_required(*, key: str) -> str:
    return f"Model task '{key}' label must be non-empty when provided."


# Local model feedback. Used by kernel/action/builtins/core/actions.py:_parse_reference_refs.
REFERENCE_REFS_LIST_REQUIRED = "Model task 'references' must be a list when provided."

# Local model feedback. Used by kernel/action/builtins/core/actions.py:_parse_reference_refs.
REFERENCE_REF_STRINGS_REQUIRED = (
    "Model task 'references' items must be non-empty strings."
)


# Local model feedback. Used by kernel/action/builtins/core/actions.py:_parse_reference_refs.
def unsupported_reference(*, item: str) -> str:
    return f"Unsupported task prompt reference ref: {item}"


# Local model feedback. Used by kernel/action/builtins/core/actions.py:_parse_reference_refs.
def empty_reference(*, item: str) -> str:
    return f"Task prompt reference produced no content: {item}"


# Local model feedback. Used by kernel/action/catalog/schema.py:_validate_value.
INVALID_ONEOF_DEFINITION = "Invalid oneOf definition"


# Local model feedback. Used by kernel/action/catalog/schema.py:_validate_value.
def parameter_variant_mismatch(*, path: str) -> str:
    return f"Action parameter {path} must match exactly one declared variant"


# Local model feedback. Used by kernel/action/catalog/schema.py:_validate_value.
def invalid_parameter_schema_type(*, path: str) -> str:
    return f"Action parameter schema type for {path} is invalid"


# Local model feedback. Used by kernel/action/catalog/schema.py:_validate_value.
def parameter_type_mismatch(*, path: str, expected_type: str) -> str:
    return f"Action parameter {path} must be {expected_type}"


# Local model feedback. Used by kernel/action/catalog/schema.py:_validate_value.
def parameter_enum_mismatch(*, path: str) -> str:
    return f"Action parameter {path} must be one of the allowed values"


# Local model feedback. Used by kernel/action/catalog/schema.py:_validate_value.
def parameter_below_minimum(*, path: str, minimum: int | float) -> str:
    return f"Action parameter {path} must be >= {minimum}"


# Local model feedback. Used by kernel/action/catalog/schema.py:_validate_value.
def parameter_above_maximum(*, path: str, maximum: int | float) -> str:
    return f"Action parameter {path} must be <= {maximum}"


# Local model feedback. Used by kernel/action/catalog/schema.py:_validate_value, kernel/action/catalog/schema.py:_validate_object.
def parameter_size_below_minimum(*, path: str, minimum: int | float) -> str:
    return f"Action parameter {path} size must be >= {minimum}"


# Local model feedback. Used by kernel/action/catalog/schema.py:_validate_value, kernel/action/catalog/schema.py:_validate_object.
def parameter_size_above_maximum(*, path: str, maximum: int | float) -> str:
    return f"Action parameter {path} size must be <= {maximum}"


# Local model feedback. Used by kernel/action/catalog/schema.py:_validate_value.
def parameter_must_be_object(*, path: str) -> str:
    return f"Action parameter {path} must be object"


# Local model feedback. Used by kernel/action/catalog/schema.py:_validate_value.
def parameter_must_be_array(*, path: str) -> str:
    return f"Action parameter {path} must be array"


# Local model feedback. Used by kernel/action/catalog/schema.py:_validate_object.
def invalid_schema_properties(*, path: str) -> str:
    return f"Action parameter schema properties for {path} is invalid"


# Local model feedback. Used by kernel/action/catalog/schema.py:_validate_object.
def invalid_schema_required(*, path: str) -> str:
    return f"Action parameter schema required for {path} is invalid"


# Local model feedback. Used by kernel/action/catalog/schema.py:_validate_object.
def missing_parameter(*, name: str) -> str:
    return f"Missing required action parameter: {name}"


# Local model feedback. Used by kernel/action/catalog/schema.py:_validate_object.
def unexpected_parameter(*, name: str) -> str:
    return f"Unexpected action parameter: {name}"


# Local model feedback. Used by kernel/action/execution/hooks.py:run.
def normalize_hook_unavailable(*, name: str) -> str:
    return f"Action normalize hook is not available: {name}"


# Local model feedback. Used by kernel/action/execution/hooks.py:_run_hook.
def normalize_hook_failed(*, name: str) -> str:
    return f"Action normalize hook failed: {name}"


# Local model feedback. Used by kernel/action/execution/hooks.py:run.
def execution_hook_unavailable(*, name: str) -> str:
    return f"Action execution hook is not available: {name}"


# Local model feedback. Used by kernel/action/execution/hooks.py:run.
def execution_hook_failed(*, name: str) -> str:
    return f"Action execution hook failed: {name}"


# Local model feedback. Used by kernel/action/execution/preparation.py:prepare_batch.
def duplicate_action_call(*, call_id: str) -> str:
    return f"Duplicate action call id: {call_id}"


# Local model feedback. Used by kernel/action/execution/preparation.py:prepare_batch.
def duplicate_action_sequence(*, sequence: int) -> str:
    return f"Duplicate action sequence: {sequence}"


# Local model feedback. Used by kernel/action/execution/preparation.py:prepare_batch.
def unknown_prepared_action(*, action_name: str) -> str:
    return f"Unknown action during preparation: {action_name}"


# Local model feedback. Used by kernel/action/execution/preparation.py:prepare_batch.
ACTION_BATCH_PREPARATION_FAILED = "Action batch preparation failed."

# Local model feedback. Used by kernel/action/execution/runner.py:_timeout_result.
ACTION_EXCEEDED_ITS_EXECUTION_DEADLINE = "Action exceeded its execution deadline."


# Local model feedback. Used by kernel/action/planning/normalization.py:normalize.
def duplicate_action_tool_call(*, call_id: str) -> str:
    return f"Duplicate action tool call id: {call_id}"


# Local model feedback. Used by kernel/action/planning/normalization.py:normalize.
EXPECTED_ACTION_TOOL_CALL = (
    "Expected an action tool call, but received a control or uncategorized tool call."
)


# Local model feedback. Used by kernel/action/planning/normalization.py:normalize.
def unknown_action_tool(*, name: str) -> str:
    return f"Unknown action tool call: {name}"


# Local model feedback. Used by kernel/action/planning/scope.py:normalize_selection.
DOMAIN_SELECTION_REQUIRED = "Phase1 must call select_action_domains."

# Local model feedback. Used by kernel/action/planning/scope.py:normalize_selection.
DUPLICATE_DOMAIN_SELECTION = "Phase1 must call select_action_domains only once."

# Local model feedback. Used by kernel/action/planning/scope.py:normalize_selection.
DOMAIN_LIST_REQUIRED = "select_action_domains.domains must be a non-empty string list."

# Local model feedback. Used by kernel/action/planning/scope.py:prepare.
ACTION_SCOPE_PREPARATION_FAILED = "Action scope preparation failed."


# Local model feedback. Used by kernel/action/tasks.py:json.
def missing_json_answer(*, subject: str) -> str:
    return f"{subject} did not return a JSON object."


# Local model feedback. Used by kernel/action/tasks.py:text.
def missing_text_answer(*, subject: str) -> str:
    return f"{subject} did not return nonempty text."


# Local model feedback. Used by kernel/action/tasks.py:text.
def artifact_limit_exceeded(*, subject: str) -> str:
    return f"{subject} exceeded its artifact limit."
