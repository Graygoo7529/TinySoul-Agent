"""Agent Home runtime copy support and trap handler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from tinysoul.runtime import (
    RunLevel,
    RuntimeTransfer,
    TrapResult,
    TrapSnap,
)

from .errors import AgentHomeContractError, AgentHomeError
from .links import parse_home_link

if TYPE_CHECKING:
    from .engine import AgentHomeEngine


@dataclass(frozen=True)
class AgentHomeRuntimeCopyTrapHandler:
    """Prepare a requested Agent Home runtime copy and retry the current frame."""

    home: "AgentHomeEngine"

    def handle(self, snap: TrapSnap) -> TrapResult:
        link_value = snap.payload.get("link")
        if isinstance(link_value, str):
            try:
                materialized = self.home.ensure_runtime_copy(
                    parse_home_link(link_value)
                )
            except AgentHomeError:
                return _end_available_scope(snap)
            current = snap.scope.current()
            if materialized and current is not None:
                return TrapResult(transfer=RuntimeTransfer.retry(current))
        return _end_available_scope(snap)


def _end_available_scope(snap: TrapSnap) -> TrapResult:
    turn = snap.scope.nearest(RunLevel.TURN)
    if turn is not None:
        return TrapResult(transfer=RuntimeTransfer.end(turn))
    program = snap.scope.nearest(RunLevel.PROGRAM)
    if program is not None:
        return TrapResult(transfer=RuntimeTransfer.end(program))
    current = snap.scope.current()
    if current is None:
        raise AgentHomeContractError("Cannot handle home runtime copy without scope")
    return TrapResult(transfer=RuntimeTransfer.end(current))
