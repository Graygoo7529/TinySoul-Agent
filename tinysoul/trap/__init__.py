"""
Trap module for TinySoul.

Provides:
- Exception hierarchy (exceptions.py)
- Central interrupt router / trap (trap.py)
- Signal system for soft interrupts (signal.py)
- Interrupt handler for state mutations (interrupt_handler.py)
"""

from .exceptions import (
    AbortError,
    ActionError,
    ActionCancelledError,
    ActionExecutionError,
    ActionInputError,
    ActionNotFoundError,
    ActionTimeoutError,
    ConfigError,
    FeedbackError,
    LLMResponseParseError,
    LLMResponseValidationError,
    LLMTransientError,
    LoopAbortError,
    PathTraversalError,
    RecoverableError,
    ResourceConflictError,
    ResourceNotFoundError,
    StateError,
    SystemExhaustedError,
    TinysoulError,
    TodoAmbiguityError,
    WorkspaceError,
)
from .interrupt_handler import InterruptHandler
from .signal import (
    Signal,
    SignalBus,
    SignalContext,
    SignalType,
)
from .trap import Disposition, ErrorContext, ErrorTrap, LoopErrorItem, TrapOutcome

__all__ = [
    # Exceptions
    "TinysoulError",
    "LoopAbortError",
    "AbortError",
    "ConfigError",
    "SystemExhaustedError",
    "RecoverableError",
    "LLMTransientError",
    "FeedbackError",
    "LLMResponseParseError",
    "LLMResponseValidationError",
    "ActionError",
    "ActionCancelledError",
    "ActionNotFoundError",
    "ActionInputError",
    "ActionExecutionError",
    "ActionTimeoutError",
    "StateError",
    "TodoAmbiguityError",
    "WorkspaceError",
    "PathTraversalError",
    "ResourceNotFoundError",
    "ResourceConflictError",
    # Trap
    "Disposition",
    "ErrorContext",
    "ErrorTrap",
    "LoopErrorItem",
    "TrapOutcome",
    # Signal
    "Signal",
    "SignalType",
    "SignalContext",
    "SignalBus",
    # Interrupt Handler
    "InterruptHandler",
]
