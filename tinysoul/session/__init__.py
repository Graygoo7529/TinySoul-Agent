"""Daily cross-Turn Session history."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .actions import register_session_actions
    from .projection import SessionTurnCompletionHandler, SessionTurnPreparationHandler
from .config import SessionSettings, parse_session_settings
from .engine import SessionArchiveSnapshot, SessionArchiveView, SessionEngine
from .errors import (
    SessionContractError,
    SessionError,
    SessionInspectFailureReason,
    SessionInspectRequestError,
    SessionIOError,
    SessionInvariantError,
)
from .failures import SessionFailureKind
from .memory import SessionMemoryFact, SessionMemoryFactsProjection
from .models import (
    SessionActionOutcome,
    SessionActionRecord,
    SessionInputRecord,
    SessionManifest,
    SessionOutputRecord,
    SessionRecordKind,
    SessionSummaryRecord,
    SessionTurnRecord,
)
from .reconcile import SessionReconcileResult

__all__ = [
    "SessionContractError",
    "SessionActionOutcome",
    "SessionActionRecord",
    "SessionArchiveSnapshot",
    "SessionEngine",
    "SessionArchiveView",
    "SessionError",
    "SessionInspectFailureReason",
    "SessionInspectRequestError",
    "SessionFailureKind",
    "SessionIOError",
    "SessionInvariantError",
    "SessionMemoryFact",
    "SessionMemoryFactsProjection",
    "SessionInputRecord",
    "SessionManifest",
    "SessionOutputRecord",
    "SessionRecordKind",
    "SessionReconcileResult",
    "SessionSettings",
    "SessionSummaryRecord",
    "SessionTurnRecord",
    "SessionTurnCompletionHandler",
    "SessionTurnPreparationHandler",
    "parse_session_settings",
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
