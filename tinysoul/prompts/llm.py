"""Model-visible text owned by llm.

Consumers listed below decide visibility, role, data and failure semantics.
"""


# Model task text or feedback. Used by llm/provider/openai_sdk/payloads.py:tool_result_text.
def tool_result_context(*, tool_name: str, content: str) -> str:
    return f"Tool result for {tool_name}:\n{content}"


# Local model feedback. Used by llm/execution/task.py:_run_task.
INPUT_CAPACITY_EXCEEDED = (
    "The complete task exceeds model input capacity; reduce the task input scope."
)

# Local model feedback. Used by llm/execution/task.py:_completion_failure.
MODEL_GENERATION_REACHED_ITS_OUTPUT_TOKEN_LIMIT = (
    "Model generation reached its output token limit."
)

# Local model feedback. Used by llm/execution/task.py:_completion_failure.
MODEL_GENERATION_WAS_STOPPED_BY_A_CONTENT_FILTER = (
    "Model generation was stopped by a content filter."
)

# Local model feedback. Used by llm/execution/task.py:_completion_failure.
INCOMPLETE_RESPONSE = "Model generation ended before producing a complete response."


# Local model feedback. Used by llm/protocol/responses.py:interpret.
def unsupported_answer_format(*, answer_format: str) -> str:
    return f"Unsupported answer format: {answer_format}"


# Local model feedback. Used by llm/protocol/responses.py:_interpret_tool_calls.
TOOL_CALLS_ARE_DISABLED_FOR_THIS_TASK = "Tool calls are disabled for this task"

# Local model feedback. Used by llm/protocol/responses.py:_interpret_tool_calls.
EXPECTED_AT_LEAST_ONE_TOOL_CALL = "Expected at least one tool call"


# Local model feedback. Used by llm/protocol/responses.py:_interpret_tool_calls.
def unsupported_tool_use(*, tool_use: str) -> str:
    return f"Unsupported tool use: {tool_use}"


# Local model feedback. Used by llm/protocol/responses.py:_validate_tool_scope.
def unexpected_tool_call(*, name: str) -> str:
    return f"Unexpected tool call: {name}"


# Local model feedback. Used by llm/protocol/responses.py:_validate_tool_scope.
def tool_kind_mismatch(*, name: str) -> str:
    return f"Tool call kind does not match its scope: {name}"


# Local model feedback. Used by llm/protocol/responses.py:_validate_tool_scope.
def missing_forced_tool(*, forced_name: str) -> str:
    return f"Expected forced tool call: {forced_name}"


# Local model feedback. Used by llm/protocol/responses.py:_parse_json_object.
def invalid_json_response(*, detail: str) -> str:
    return f"Failed to parse model response as JSON object: {detail}"


# Local model feedback. Used by llm/protocol/responses.py:_parse_json_object.
def expected_json_object(*, type_name: str) -> str:
    return f"Expected JSON object, got {type_name}"
