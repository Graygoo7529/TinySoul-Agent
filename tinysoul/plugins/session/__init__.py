"""Daily cross-Turn Session history."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .projection import SessionTurnCompletionHandler
from .config import SessionSettings, parse_session_settings
from .engine import SessionArchiveSnapshot, SessionEngine
from .views import SessionView
from .errors import (
    SessionContractError,
    SessionError,
    SessionInspectFailureReason,
    SessionInspectRequestError,
    SessionIOError,
    SessionInvariantError,
)
from .failures import SessionFailureKind
from .views.memory import SessionMemoryFact, SessionMemoryFactsProjection
from .records.models import (
    SessionActionOutcome,
    SessionActionRecord,
    SessionInputRecord,
    SessionManifest,
    SessionOutputRecord,
    SessionRecordKind,
    SessionTurnRecord,
)
from .records.reconcile import SessionReconcileResult

__all__ = [
    "SessionContractError",
    "SessionActionOutcome",
    "SessionActionRecord",
    "SessionArchiveSnapshot",
    "SessionEngine",
    "SessionView",
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
    "SessionTurnRecord",
    "SessionTurnCompletionHandler",
    "parse_session_settings",
]


def __getattr__(name: str) -> object:
    if name == "SessionTurnCompletionHandler":
        from .projection import SessionTurnCompletionHandler

        return SessionTurnCompletionHandler
    raise AttributeError(name)
