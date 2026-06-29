"""Trap primitives for TinySoul runtime."""

from .snap import TrapSnap
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
