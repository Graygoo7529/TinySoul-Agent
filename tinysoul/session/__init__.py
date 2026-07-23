"""Daily cross-Turn Session history."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .actions import register_session_actions
    from .projection import SessionTurnCompletionHandler, SessionTurnPreparationHandler
from .config import SessionSettings, parse_session_settings
from .action_history import (
    ActionPairingIssue,
    TurnActionDetail,
    TurnActionProjection,
    project_turn_actions,
)
from .engine import SessionArchiveSnapshot, SessionEngine
from .errors import (
    SessionContractError,
    SessionError,
    SessionHistoryFailureReason,
    SessionHistoryRequestError,
    SessionIOError,
    SessionInvariantError,
)
from .failures import SessionFailureKind
from .memory import SessionMemoryFact, SessionMemoryFactsProjection
from .reconcile import SessionReconcileResult

__all__ = [
    "SessionContractError",
    "ActionPairingIssue",
    "SessionArchiveSnapshot",
    "SessionEngine",
    "SessionError",
    "SessionHistoryFailureReason",
    "SessionHistoryRequestError",
    "SessionFailureKind",
    "SessionIOError",
    "SessionInvariantError",
    "SessionMemoryFact",
    "SessionMemoryFactsProjection",
    "SessionReconcileResult",
    "SessionSettings",
    "SessionTurnCompletionHandler",
    "SessionTurnPreparationHandler",
    "TurnActionDetail",
    "TurnActionProjection",
    "parse_session_settings",
    "project_turn_actions",
    "register_session_actions",
]


def __getattr__(name: str) -> object:
    if name == "register_session_actions":
        from .actions import register_session_actions

        return register_session_actions
    if name == "SessionTurnCompletionHandler":
        from .projection import SessionTurnCompletionHandler

        return SessionTurnCompletionHandler
    if name == "SessionTurnPreparationHandler":
        from .projection import SessionTurnPreparationHandler

        return SessionTurnPreparationHandler
    raise AttributeError(name)
