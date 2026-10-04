"""Model-visible text owned by plugins.execution.

Consumers listed below decide visibility, role, data and failure semantics.
"""

# Local model feedback. Used by plugins/execution/actions.py:execute.
THE_EXECUTION_REQUEST_IS_UNAVAILABLE_OR_INVALID = (
    "The execution request is unavailable or invalid."
)

# Local model feedback. Used by plugins/execution/actions.py:execute.
THE_REQUESTED_PROCESS_COULD_NOT_START = "The requested process could not start."

# Local model feedback. Used by plugins/execution/actions.py:_execute.
PROCESS_EXECUTION_FAILED = (
    "Process execution failed; existing Workspace effects remain available."
)
