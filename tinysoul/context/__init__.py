"""
Runtime module for TinySoul.

Provides runtime state, workspace, and protocol definitions for the agent query loop.
"""

from .protocols import ContextProvider
from .ongoing import OngoingControl, OngoingControlRegistry
from .state.state import QueryState
from .state.todo import TodoItem
from .workspace.workspace import Workspace

__all__ = [
    "ContextProvider",
    "OngoingControl",
    "OngoingControlRegistry",
    "QueryState",
    "TodoItem",
    "Workspace",
]
