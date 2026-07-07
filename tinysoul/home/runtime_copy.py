"""Agent Home runtime copy support and trap handler."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from tinysoul.infra.filesystem import copy_file
from tinysoul.runtime import RunLevel, RuntimeTransfer, TrapResult, TrapSnap

from .errors import AgentHomeContractError, AgentHomeError, AgentHomeIOError
from .links import parse_home_link

if TYPE_CHECKING:
    from .engine import AgentHomeEngine


class AgentHomeRuntimeCopyManager:
    """Prepare writable runtime copies for Agent Home source files."""

    def ensure_source_copy(self, source: Path, runtime: Path) -> Path:
        if runtime.exists():
            return runtime
        if not source.is_file():
            raise AgentHomeContractError(f"Home source file does not exist: {source}")
        try:
            copy_file(source, runtime)
        except OSError as exc:
            raise AgentHomeIOError(f"Failed to copy home resource: {exc}") from exc
        return runtime


@dataclass(frozen=True)
class AgentHomeRuntimeCopyTrapHandler:
    """Prepare a requested Agent Home runtime copy and retry the current frame."""

    home: "AgentHomeEngine"

    def handle(self, snap: TrapSnap) -> TrapResult:
        link_value = snap.payload.get("link")
        if isinstance(link_value, str):
            try:
                self.home.ensure_runtime_copy(parse_home_link(link_value))
            except AgentHomeError:
                return _end_available_scope(snap)
            current = snap.scope.current()
            if current is not None:
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
