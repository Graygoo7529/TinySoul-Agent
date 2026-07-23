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
    SIGNAL_WORKSPACE_SYNC,
    build_input_append_signal,
    build_session_sync_signal,
    build_trace_action_result_signal,
    build_trace_decision_signal,
    build_trace_phase_note_signal,
    build_workspace_sync_signal,
    parse_input_append_signal,
)
from .working import WorkspaceResource, WorkspaceSnapshot
from .background import SessionBackgroundItem, SessionBackgroundSnapshot
from .composer import ContextBudgetReport, ContextSection, ContextSectionUsage
from .compress import ContextPressureReport
from .trace import canonical_trace_digest, is_canonical_trace_digest

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
    "ContextSignalBatch",
    "ContextSettings",
    "ContextSection",
    "ContextSectionUsage",
    "ContextPressureReport",
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
    "SIGNAL_WORKSPACE_SYNC",
    "StaticBackgroundContentLoader",
    "SessionBackgroundItem",
    "SessionBackgroundSnapshot",
    "TaskPrompt",
    "TurnSummary",
    "WorkspaceResource",
    "WorkspaceSnapshot",
    "build_input_append_signal",
    "build_session_sync_signal",
    "build_trace_action_result_signal",
    "build_trace_decision_signal",
    "build_trace_phase_note_signal",
    "build_workspace_sync_signal",
    "canonical_trace_digest",
    "is_canonical_trace_digest",
    "parse_context_settings",
    "parse_input_append_signal",
    "register_context_actions",
]


def __getattr__(name: str) -> object:
    if name == "register_context_actions":
        from .actions import register_context_actions

        return register_context_actions
    raise AttributeError(name)
