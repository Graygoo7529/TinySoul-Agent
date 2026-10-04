"""Model-visible text owned by plugins.capabilities.expand.

Consumers listed below decide visibility, role, data and failure semantics.
"""

# Local model feedback. Used by plugins/capabilities/expand/actions.py:execute.
REMOTE_TOOL_REPORTED_A_FAILURE = "Remote tool reported a failure."

# Local model feedback. Used by plugins/capabilities/expand/actions.py:_execute.
PROVIDE_A_SERVER_TOOL_NAME_AND_ARGUMENT_OBJECT = (
    "Provide a server, tool name and argument object."
)

# Local model feedback. Used by plugins/capabilities/expand/actions.py:_execute.
TOOL_SEARCH_IS_NOT_CONFIGURED = "Tool search is not configured"

# Local model feedback. Used by plugins/capabilities/expand/actions.py:_execute.
PAGE_IDENTITY_IS_INVALID = "Page identity is invalid."

# Local model feedback. Used by plugins/capabilities/expand/actions.py:_execute.
PROVIDE_TOOLS_OR_SERVER_IDS_EXACTLY_ONE_SELECTOR = (
    "Provide tools or server_ids, exactly one selector."
)

# Local model feedback. Used by plugins/capabilities/expand/actions.py:_execute.
UNSUPPORTED_DIRECTORY_OPERATION = "Unsupported directory operation"

# Local model feedback. Used by plugins/capabilities/expand/actions.py:_server_ids.
SERVER_IDS_MUST_BE_A_NON_EMPTY_BOUNDED_LIST = (
    "server_ids must be a non-empty bounded list."
)

# Local model feedback. Used by plugins/capabilities/expand/actions.py:_tool_ids.
TOOLS_MUST_CONTAIN_BOUNDED_STRUCTURED_IDENTITIES = (
    "tools must contain bounded structured identities."
)

# Local model feedback. Used by plugins/capabilities/expand/actions.py:_tool_ids.
EACH_TOOL_REQUIRES_SERVER_ID_AND_TOOL_NAME = (
    "Each tool requires server_id and tool_name."
)

# Local model feedback. Used by plugins/capabilities/expand/engine.py:tools_view.
UNKNOWN_MCP_SERVER = "Unknown MCP server"

# Local model feedback. Used by plugins/capabilities/expand/engine.py:refresh.
MCP_SERVER_IS_NOT_ENABLED = "MCP server is not enabled"

# Local model feedback. Used by plugins/capabilities/expand/engine.py:search_corpus.
MCP_SEARCH_USES_A_DECLARED_SERVER_TOOL_DIRECTORY = (
    "MCP search uses a declared server/tool directory"
)

# Local model feedback. Used by plugins/capabilities/expand/engine.py:search_corpus.
MCP_SCOPE_MUST_BE_ALL_OR_SERVER_ID = "MCP scope must be all or server:<id>"

# Local model feedback. Used by plugins/capabilities/expand/engine.py:search_corpus.
SELECTED_SERVER_UNAVAILABLE = (
    "A selected MCP server is unavailable; choose an available server scope"
)

# Local model feedback. Used by plugins/capabilities/expand/engine.py:search_corpus.
MCP_REF_IS_NOT_AVAILABLE_IN_THE_TOOL_DIRECTORY = (
    "MCP ref is not available in the tool directory"
)

# Local model feedback. Used by plugins/capabilities/expand/engine.py:search_corpus.
DIRECTORY_CAPACITY_EXCEEDED = (
    "MCP candidate directory exceeds input capacity; narrow server scope or browse "
    "describe_servers"
)

# Local model feedback. Used by plugins/capabilities/expand/engine.py:page.
DIRECTORY_PAGE_EXPIRED_DESCRIBE_THE_SCOPE_AGAIN = (
    "Directory page expired; describe the scope again."
)

# Local model feedback. Used by plugins/capabilities/expand/engine.py:page.
DIRECTORY_ITEM_EXCEEDS_RESPONSE_CAPACITY = "Directory item exceeds response capacity."

# Local model feedback. Used by plugins/capabilities/expand/engine.py:call.
TOOL_IS_UNAVAILABLE_OR_EXCLUDED_BY_SERVER_POLICY = (
    "Tool is unavailable or excluded by server policy."
)

# Local model feedback. Used by plugins/capabilities/expand/engine.py:call.
UNSUPPORTED_TOOL_DEFINITION = "Tool definition is unsupported or exceeds its bound."

# Local model feedback. Used by plugins/capabilities/expand/engine.py:call.
ARGUMENTS_DO_NOT_SATISFY_THE_TOOL_DEFINITION = (
    "Arguments do not satisfy the tool definition."
)

# Local model feedback. Used by plugins/capabilities/expand/engine.py:call.
TOOL_SCHEMA_COULD_NOT_BE_RESOLVED = "Tool schema could not be resolved."

# Local model feedback. Used by plugins/capabilities/expand/engine.py:call.
INVALID_TOOL_OUTPUT = "Tool returned output that does not satisfy its schema."

# Local model feedback. Used by plugins/capabilities/expand/engine.py:_project_result.
TOOL_OUTPUT_LIMIT_EXCEEDED = (
    "Tool result exceeds the configured output bound; effects may already exist."
)

# Local model feedback. Used by plugins/capabilities/expand/engine.py:_project_result.
TOOL_CONTENT_IS_INVALID = "Tool content is invalid."

# Local model feedback. Used by plugins/capabilities/expand/engine.py:_project_result.
TOOL_RETURNED_INVALID_EMBEDDED_CONTENT = "Tool returned invalid embedded content."

# Local model feedback. Used by plugins/capabilities/expand/mcp/client.py:_serve.
MCP_SERVER_COULD_NOT_CONNECT = "MCP server could not connect."

# Local model feedback. Used by plugins/capabilities/expand/mcp/client.py:_connect.
MCP_CONNECTION_TIMED_OUT = "MCP connection timed out."

# Local model feedback. Used by plugins/capabilities/expand/mcp/client.py:directory.
SERVER_DIRECTORY_LIMIT_EXCEEDED = "Server tool directory exceeds its configured bound."

# Local model feedback. Used by plugins/capabilities/expand/mcp/client.py:directory.
SERVER_TOOL_PAGINATION_DID_NOT_CONVERGE = "Server tool pagination did not converge."

# Local model feedback. Used by plugins/capabilities/expand/mcp/client.py:directory.
MCP_TOOL_DIRECTORY_IS_UNAVAILABLE = "MCP tool directory is unavailable."

# Local model feedback. Used by plugins/capabilities/expand/mcp/client.py:call.
UNSUPPORTED_INPUT_EXCHANGE = (
    "MCP tool requires an unsupported input exchange; no continuation was sent. "
    "External effects may already exist."
)

# Local model feedback. Used by plugins/capabilities/expand/mcp/client.py:call.
MCP_CALL_RESULT_UNAVAILABLE = (
    "MCP call did not return a usable result; external effects may already exist. "
    "Inspect before retrying."
)
