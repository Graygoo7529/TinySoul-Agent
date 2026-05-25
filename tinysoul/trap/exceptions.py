"""
Unified exception hierarchy for TinySoul.

Design principles:
1. All framework errors inherit from TinysoulError.
2. KeyboardInterrupt and SystemExit are NEVER caught by business logic.
3. Three-tier taxonomy: AbortError, RecoverableError, FeedbackError.
4. ActionError, StateError, WorkspaceError are peers under FeedbackError.
   WorkspaceError is a subclass of ActionExecutionError because workspace
   operations are almost always part of action execution.
5. Errors carry their own context (action_name, action_input) at raise time.
"""

# ============================================================================
# Base
# ============================================================================


class TinysoulError(Exception):
    """Base exception for all TinySoul framework errors."""

    pass


# ============================================================================
# 1. AbortError — fatal errors that terminate the loop/system
# ============================================================================


class AbortError(TinysoulError):
    """Fatal error: the query loop must terminate."""

    pass


class ConfigError(AbortError):
    """Configuration error that prevents the system from starting."""

    pass


class SystemExhaustedError(AbortError):
    """All recovery mechanisms exhausted (e.g., every LLM model failed)."""

    pass


class LoopAbortError(AbortError):
    """Raised when the query loop should be aborted."""

    pass


# ============================================================================
# 2. RecoverableError — can be handled automatically without LLM awareness
# ============================================================================


class RecoverableError(TinysoulError):
    """Errors that can be handled automatically without LLM feedback."""

    pass


class LLMTransientError(RecoverableError):
    """LLM provider call failed transiently (network, timeout, rate limit).

    AIClient will retry internally; ErrorTrap will drive failover.
    """

    def __init__(self, message: str, *, model_name: str = ""):
        self.model_name = model_name
        super().__init__(message)


# ============================================================================
# 3. FeedbackError — must be fed back to the LLM so it can adjust strategy
# ============================================================================


class FeedbackError(TinysoulError):
    """Errors that must be fed back to the LLM.

    Protocol: action_name and action_input are set at raise time
    when the error occurs within an action execution context.
    """

    def __init__(
        self,
        message: str,
        *,
        action_name: str | None = None,
        action_input: dict | None = None,
        cause: Exception | None = None,
    ):
        self.action_name = action_name
        self.action_input = action_input
        super().__init__(message)
        self.__cause__ = cause

    def to_loop_error_message(self) -> str:
        """Standardised message for loop_error_list."""
        import json

        parts = []
        if self.action_name:
            parts.append(f"action={self.action_name}")
        if self.action_input is not None:
            parts.append(f"input={json.dumps(self.action_input, ensure_ascii=False)}")
        parts.append(f"error={str(self)}")
        return " | ".join(parts)


# ============================================================================
# 4. LLM Response Errors
# ============================================================================


class LLMResponseParseError(FeedbackError):
    """LLM returned raw text that cannot be parsed into structured data."""

    pass


class LLMResponseValidationError(FeedbackError):
    """LLM returned structured data that fails semantic / schema validation."""

    pass


# ============================================================================
# 5. ActionError — errors during action execution (peer of StateError)
# ============================================================================


class ActionError(FeedbackError):
    """Root of all errors occurring during action execution.

    ActionErrors are recorded to BOTH loop_error_list and action_record_list.
    Protocol: action_name and action_input are set at raise time.
    """

    pass


class ActionNotFoundError(ActionError):
    """Requested action is not available in the current query context."""

    pass


class ActionInputError(ActionError):
    """Action input parsing or validation failed."""

    pass


class ActionExecutionError(ActionError):
    """Action execution logic failed."""

    pass


class ActionTimeoutError(ActionExecutionError):
    """Action execution exceeded its configured timeout."""

    pass


class ActionCancelledError(ActionExecutionError):
    """Action execution was cancelled by the dispatcher or controller."""

    pass


# ============================================================================
# 6. WorkspaceError — errors during workspace operations UNDER ActionExecutionError
# ============================================================================


class WorkspaceError(ActionExecutionError):
    """Workspace operation failed during action execution."""

    pass


class PathTraversalError(WorkspaceError):
    """Resource access resolves outside workspace boundary."""

    pass


class ResourceNotFoundError(WorkspaceError):
    """Resource not found in workspace."""

    pass


class ResourceConflictError(WorkspaceError):
    """Resource already exists in workspace."""

    pass


# ============================================================================
# 7. StateError — errors during state operations (peer of ActionError)
# ============================================================================


class StateError(FeedbackError):
    """State operation failed."""

    pass


class TodoAmbiguityError(StateError):
    """Todo key matches multiple pending todos."""

    pass
