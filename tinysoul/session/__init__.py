"""Daily cross-Turn Session history."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .actions import register_session_actions
    from .projection import SessionTurnCompletionHandler, SessionTurnPreparationHandler
from .config import SessionSettings, parse_session_settings
from .engine import SessionEngine
from .errors import (
    SessionContractError,
    SessionError,
    SessionIOError,
    SessionInvariantError,
)
from .failures import SessionFailureKind

__all__ = [
    "SessionContractError",
    "SessionEngine",
    "SessionError",
    "SessionFailureKind",
    "SessionIOError",
    "SessionInvariantError",
    "SessionSettings",
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
