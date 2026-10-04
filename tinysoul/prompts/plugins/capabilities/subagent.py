"""Model-visible text owned by plugins.capabilities.subagent.

Consumers listed below decide visibility, role, data and failure semantics.
"""


# Model context presentation or local feedback. Used by plugins/capabilities/subagent/engine.py:prepare_brief.
def delegation_reference(*, link: str, text: str) -> str:
    return f"Reference {link}:\n{text}"


# Local model feedback. Used by plugins/capabilities/subagent/acp/connection.py:prompt.
ACP_SESSION_IS_NOT_READY_FOR_A_NEW_DELEGATION = (
    "ACP session is not ready for a new delegation."
)

# Local model feedback. Used by plugins/capabilities/subagent/actions.py:execute.
RESOURCE_UNAVAILABLE = "The requested resource is unavailable in this Turn."

# Local model feedback. Used by plugins/capabilities/subagent/actions.py:text.
REQUIRED_ACTION_TEXT_OR_IDENTITY_IS_ABSENT = (
    "Required action text or identity is absent."
)

# Local model feedback. Used by plugins/capabilities/subagent/actions.py:_execute.
REFERENCE_LINKS_MUST_BE_A_BOUNDED_LIST = "Reference links must be a bounded list."

# Local model feedback. Used by plugins/capabilities/subagent/actions.py:_execute.
COLLECTION_CURSOR_MUST_BE_AN_INTEGER = "Collection cursor must be an integer."

# Local model feedback. Used by plugins/capabilities/subagent/engine.py:connect.
CONFIGURED_AGENT_TARGET_IS_UNAVAILABLE = "Configured Agent target is unavailable."

# Local model feedback. Used by plugins/capabilities/subagent/engine.py:connect.
EXTERNAL_AGENT_SESSION_COULD_NOT_BE_CREATED = (
    "External Agent session could not be created."
)

# Local model feedback. Used by plugins/capabilities/subagent/engine.py:connect.
CONNECTION_CAPACITY_EXCEEDED = (
    "Connection capacity is full; disconnect an idle connection."
)

# Local model feedback. Used by plugins/capabilities/subagent/engine.py:connect.
EXTERNAL_AGENT_CONNECTION_FAILED = (
    "External Agent could not connect; check its local setup and authentication."
)

# Local model feedback. Used by plugins/capabilities/subagent/engine.py:_owned.
CONNECTION_IS_UNAVAILABLE_IN_THIS_TURN = "Connection is unavailable in this Turn."

# Local model feedback. Used by plugins/capabilities/subagent/engine.py:delegate.
CONNECTION_IS_BUSY_OR_CLOSED = "Connection is busy or closed."

# Local model feedback. Used by plugins/capabilities/subagent/engine.py:delegate.
DELEGATION_REQUIRES_A_BOUNDED_NON_EMPTY_BRIEF = (
    "Delegation requires a bounded non-empty brief."
)

# Local model feedback. Used by plugins/capabilities/subagent/engine.py:prepare_brief.
WORKSPACE_REFERENCE_REQUIRED = "Delegation references must name Workspace resources."

# Local model feedback. Used by plugins/capabilities/subagent/engine.py:prepare_brief.
REFERENCE_INPUT_LIMIT_EXCEEDED = (
    "Reference exceeds the delegation input bound; provide a smaller resource."
)

# Local model feedback. Used by plugins/capabilities/subagent/engine.py:prepare_brief.
DELEGATION_INPUT_EXCEEDS_ITS_BOUND = "Delegation input exceeds its bound."

# Local model feedback. Used by plugins/capabilities/subagent/engine.py:disconnect.
ACTIVE_JOB_BLOCKS_DISCONNECTION = (
    "Stop or finish the connection's Job before disconnecting."
)

# Local model feedback. Used by plugins/capabilities/subagent/engine.py:close_turn.
JOBS_MUST_CLOSE_BEFORE_THEIR_SESSIONS = "Jobs must close before their sessions."

# Local model feedback. Used by plugins/capabilities/subagent/jobs/backend.py:respond.
PERMISSION_REQUEST_OR_OPTION_IS_NO_LONGER_AVAILABLE = (
    "Permission request or option is no longer available."
)

# Local model feedback. Used by plugins/capabilities/subagent/jobs/backend.py:collect.
OUTPUT_CURSOR_IS_UNAVAILABLE = "Output cursor is unavailable."

# Local model feedback. Used by plugins/capabilities/subagent/jobs/backend.py:read_output.
BACKEND_OUTPUT_CURSOR_IS_UNAVAILABLE = "Output cursor is unavailable"
