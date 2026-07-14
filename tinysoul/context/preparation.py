"""Context-owned Turn preparation integration."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.loop.preparation import TurnPreparationRequest
from tinysoul.runtime import Signal
from tinysoul.runtime.bridge import RuntimeContextBridge

from .engine import ContextEngine
from .errors import ContextError


@dataclass(frozen=True)
class ContextTurnPreparationHandler:
    context: ContextEngine
    runtime_bridge: RuntimeContextBridge

    def prepare(self, request: TurnPreparationRequest) -> tuple[Signal, ...]:
        try:
            self.context.prepare_default_background(request.business_day.value)
        except ContextError as exc:
            raise self.runtime_bridge.from_context_error(exc) from exc
        return ()
