"""TinySoul context module."""

from .background import BackgroundContext, BackgroundEntry, BackgroundPatch, BackgroundSource
from .composer import ContextBudget, MessageStackComposer, estimate_chars
from .compress import ContextCompressor
from .controls import (
    CONTROL_EVICT_BACKGROUND,
    CONTROL_LOAD_BACKGROUND,
    CONTROL_UPDATE_WORKING,
    ContextControlScopeBuilder,
    ControlCallNormalizer,
    ControlNormalization,
    ControlResult,
    ControlResultStage,
    ControlResultStatus,
)
from .engine import ContextEngine, ContextEngineBuilder, TurnSummary
from .errors import (
    ContextBudgetError,
    ContextContractError,
    ContextError,
    ContextInvariantError,
)
from .failures import ContextFailureKind
from .prompts import TaskPrompt
from .signals import (
    SIGNAL_BACKGROUND_PATCH,
    SIGNAL_INPUT_APPEND,
    SIGNAL_NAMESPACE,
    SIGNAL_TRACE_APPEND,
    SIGNAL_WORKING_PATCH,
    build_input_append_signal,
    build_trace_action_result_signal,
    build_trace_decision_signal,
    build_trace_phase_note_signal,
)
from .trace import (
    CompressionReport,
    PendingInput,
    PendingInputs,
    TraceEntry,
    TraceKind,
    TurnTraceContext,
)
from .working import (
    Milestone,
    TodoItem,
    TodoStatus,
    WorkingContext,
    WorkingPatch,
    WorkspaceResource,
)

__all__ = [
    "BackgroundContext",
    "BackgroundEntry",
    "BackgroundPatch",
    "BackgroundSource",
    "CompressionReport",
    "CONTROL_EVICT_BACKGROUND",
    "CONTROL_LOAD_BACKGROUND",
    "CONTROL_UPDATE_WORKING",
    "ContextBudget",
    "ContextBudgetError",
    "ContextCompressor",
    "ContextContractError",
    "ContextControlScopeBuilder",
    "ContextEngine",
    "ContextEngineBuilder",
    "ContextError",
    "ContextFailureKind",
    "ContextInvariantError",
    "ControlCallNormalizer",
    "ControlNormalization",
    "ControlResult",
    "ControlResultStage",
    "ControlResultStatus",
    "estimate_chars",
    "MessageStackComposer",
    "Milestone",
    "PendingInput",
    "PendingInputs",
    "SIGNAL_BACKGROUND_PATCH",
    "SIGNAL_INPUT_APPEND",
    "SIGNAL_NAMESPACE",
    "SIGNAL_TRACE_APPEND",
    "SIGNAL_WORKING_PATCH",
    "TaskPrompt",
    "TodoItem",
    "TodoStatus",
    "TraceEntry",
    "TraceKind",
    "TurnSummary",
    "TurnTraceContext",
    "WorkingContext",
    "WorkingPatch",
    "WorkspaceResource",
    "build_input_append_signal",
    "build_trace_action_result_signal",
    "build_trace_decision_signal",
    "build_trace_phase_note_signal",
]
