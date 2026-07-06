"""TinySoul context module."""

from .controls import (
    CONTROL_EVICT_BACKGROUND,
    CONTROL_LOAD_BACKGROUND,
    CONTROL_UPDATE_WORKING,
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
from .trace import CompressionReport, TraceKind

__all__ = [
    "CompressionReport",
    "CONTROL_EVICT_BACKGROUND",
    "CONTROL_LOAD_BACKGROUND",
    "CONTROL_UPDATE_WORKING",
    "ContextBudgetError",
    "ContextContractError",
    "ContextEngine",
    "ContextEngineBuilder",
    "ContextError",
    "ContextFailureKind",
    "ContextInvariantError",
    "ControlNormalization",
    "ControlResult",
    "ControlResultStage",
    "ControlResultStatus",
    "SIGNAL_BACKGROUND_PATCH",
    "SIGNAL_INPUT_APPEND",
    "SIGNAL_NAMESPACE",
    "SIGNAL_TRACE_APPEND",
    "SIGNAL_WORKING_PATCH",
    "TaskPrompt",
    "TraceKind",
    "TurnSummary",
    "build_input_append_signal",
    "build_trace_action_result_signal",
    "build_trace_decision_signal",
    "build_trace_phase_note_signal",
]
