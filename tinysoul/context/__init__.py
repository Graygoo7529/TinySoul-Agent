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
from .engine import (
    BackgroundContentLoader,
    ContextEngine,
    ContextEngineBuilder,
    ContextSignalBatch,
    StaticBackgroundContentLoader,
    TurnSummary,
)
from .config import ContextSettings, parse_context_settings
from .errors import (
    ContextBudgetError,
    ContextContractError,
    ContextError,
    ContextInvariantError,
)
from .failures import ContextFailureKind
from .prompts import PromptBlock, TaskPrompt
from .references import PromptReferenceError, PromptReferenceResolver
from .signals import (
    SIGNAL_BACKGROUND_PATCH,
    SIGNAL_INPUT_APPEND,
    SIGNAL_NAMESPACE,
    SIGNAL_TRACE_APPEND,
    SIGNAL_WORKING_PATCH,
    SIGNAL_WORKSPACE_SYNC,
    build_input_append_signal,
    build_trace_action_result_signal,
    build_trace_decision_signal,
    build_trace_phase_note_signal,
    build_workspace_sync_signal,
)
from .working import WorkspaceResource, WorkspaceSnapshot
from .trace import CompressionReport, TraceKind

__all__ = [
    "CompressionReport",
    "BackgroundContentLoader",
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
    "ContextSignalBatch",
    "ContextSettings",
    "ControlNormalization",
    "ControlResult",
    "ControlResultStage",
    "ControlResultStatus",
    "PromptBlock",
    "PromptReferenceError",
    "PromptReferenceResolver",
    "SIGNAL_BACKGROUND_PATCH",
    "SIGNAL_INPUT_APPEND",
    "SIGNAL_NAMESPACE",
    "SIGNAL_TRACE_APPEND",
    "SIGNAL_WORKING_PATCH",
    "SIGNAL_WORKSPACE_SYNC",
    "StaticBackgroundContentLoader",
    "TaskPrompt",
    "TraceKind",
    "TurnSummary",
    "WorkspaceResource",
    "WorkspaceSnapshot",
    "build_input_append_signal",
    "build_trace_action_result_signal",
    "build_trace_decision_signal",
    "build_trace_phase_note_signal",
    "build_workspace_sync_signal",
    "parse_context_settings",
]
