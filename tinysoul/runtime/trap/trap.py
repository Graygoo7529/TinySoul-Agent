"""Runtime trap controller."""

from __future__ import annotations

from ..exception import RuntimeException
from ..scope import RunScope
from .snap import TrapSnap
from .handler import TrapResult
from .registry import TrapHandlerRegistry


class RuntimeTrap:
    """OS-style trap controller for runtime exceptions."""

    def __init__(self, *, registry: TrapHandlerRegistry) -> None:
        self._registry = registry

    def capture(self, exception: RuntimeException, scope: RunScope) -> TrapResult:
        snap = TrapSnap.from_exception(exception, scope)
        handler = self._registry.handler_for(snap.reason)
        return handler.handle(snap)
