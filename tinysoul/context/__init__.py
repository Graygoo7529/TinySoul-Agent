"""TinySoul context module."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .actions import register_context_actions

from .controls import (
    CONTROL_EVICT_BACKGROUND,
    CONTROL_LOAD_BACKGROUND,
    CONTROL_REMOVE_MILESTONE,
    CONTROL_REMOVE_TODO,
    CONTROL_SET_MILESTONE,
    CONTROL_SET_TODO,
    ControlNormalization,
    ControlResult,
    ControlResultStage,
    ControlResultStatus,
)
from .engine import (
    BackgroundContentLoader,
    ContextTurnCompletion,
    ContextTurnInput,
    ContextEngine,
    ContextEngineBuilder,
    ContextSignalBatch,
    StaticBackgroundContentLoader,
)
from .config import ContextSettings, parse_context_settings
from .errors import (
    ContextBudgetError,
    ContextContractError,
    ContextError,
    ContextInvariantError,
    ContextTraceFailureReason,
    ContextTraceRequestError,
)
from .prompts import PromptBlock, TaskPrompt
from .preparation import ContextTurnPreparationHandler
from .providers import (
    BackgroundCatalog,
    BackgroundCatalogItem,
    BackgroundEntryProvider,
)
from .references import PromptReferenceError, PromptReferenceResolver
from .signals import (
    SIGNAL_BACKGROUND_PATCH,
    SIGNAL_INPUT_APPEND,
    SIGNAL_NAMESPACE,
    SIGNAL_SESSION_SYNC,
    SIGNAL_TRACE_APPEND,
    SIGNAL_WORKING_PATCH,
    build_input_append_signal,
    build_session_sync_signal,
    build_trace_action_result_signal,
    build_trace_decision_signal,
    build_trace_phase_note_signal,
    parse_input_append_signal,
)
from .background import SessionBackgroundItem, SessionBackgroundSnapshot
from .composer import ContextBudgetReport, ContextSectionUsage
from .compress import ContextPressureReport
from .segments import ContextSegment, SegmentRegistry

__all__ = [
    "ContextBudgetReport",
    "BackgroundContentLoader",
    "BackgroundCatalog",
    "BackgroundCatalogItem",
    "BackgroundEntryProvider",
    "CONTROL_EVICT_BACKGROUND",
    "CONTROL_LOAD_BACKGROUND",
    "CONTROL_REMOVE_MILESTONE",
    "CONTROL_REMOVE_TODO",
    "CONTROL_SET_MILESTONE",
    "CONTROL_SET_TODO",
    "ContextBudgetError",
    "ContextContractError",
    "ContextEngine",
    "ContextEngineBuilder",
    "ContextError",
    "ContextInvariantError",
    "ContextTraceFailureReason",
    "ContextTraceRequestError",
    "ContextTurnCompletion",
    "ContextTurnInput",
    "ContextSignalBatch",
    "ContextSettings",
    "ContextSectionUsage",
    "ContextPressureReport",
    "ContextSegment",
    "SegmentRegistry",
    "ContextTurnPreparationHandler",
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
    "SIGNAL_SESSION_SYNC",
    "SIGNAL_TRACE_APPEND",
    "SIGNAL_WORKING_PATCH",
    "StaticBackgroundContentLoader",
    "SessionBackgroundItem",
    "SessionBackgroundSnapshot",
    "TaskPrompt",
    "build_input_append_signal",
    "build_session_sync_signal",
    "build_trace_action_result_signal",
    "build_trace_decision_signal",
    "build_trace_phase_note_signal",
    "parse_context_settings",
    "parse_input_append_signal",
    "register_context_actions",
]


def __getattr__(name: str) -> object:
    if name == "register_context_actions":
        from .actions import register_context_actions

        return register_context_actions
    raise AttributeError(name)
