"""Model-visible text owned by plugins.execution.

Consumers listed below decide visibility, role, data and failure semantics.
"""


# Tool description. Used by plugins/execution/actions.py:register_execution_actions.
def available_interpreters_hint(*, names: tuple[str, ...]) -> str:
    available = "Available in this runtime: " + ", ".join(names) + ". "
    shells = tuple(name for name in names if name != "python")
    if not shells:
        return available + "Use source_ref; inline commands are unavailable."
    choices = " or ".join(shells)
    suffix = "; Python uses source_ref." if "python" in names else "."
    return available + f"Inline commands use {choices}" + suffix


# Local feedback. Used by plugins/execution/engine.py:start.
def interpreter_unavailable(*, interpreter: str, available: tuple[str, ...]) -> str:
    return (
        f"The {interpreter} interpreter is not enabled in this runtime. "
        f"Available interpreters: {', '.join(available) or 'none'}."
    )


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
