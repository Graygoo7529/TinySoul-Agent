"""Trap primitives for TinySoul runtime."""

from .context import TrapSnap
from .handler import TrapHandler, TrapResult
from .registry import TrapHandlerRegistry
from .trap import RuntimeTrap

__all__ = [
    "RuntimeTrap",
    "TrapHandler",
    "TrapHandlerRegistry",
    "TrapResult",
    "TrapSnap",
]
