"""Runtime execution support for replayable module frames."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from .errors import RuntimeInvariantError
from .exception import RuntimeException
from .scope import RunLevel, RunScope
from .signals.bus import SignalBus
from .transfer import RuntimeTransfer, RuntimeTransferAction
from .trap.trap import RuntimeTrap

T = TypeVar("T")


@dataclass(frozen=True)
class RuntimeTransferInterrupt(Exception):
    """Unwind an already-resolved transfer to the runner that owns its frame."""

    transfer: RuntimeTransfer


@dataclass(frozen=True)
class RuntimeModuleRunner:
    """Run a replayable module call and consume transfers targeting that call."""

    trap: RuntimeTrap
    bus: SignalBus

    def run(
        self,
        *,
        scope: RunScope,
        name: str,
        callback: Callable[[RunScope], T],
    ) -> T:
        module_scope = scope.push(RunLevel.MODULE, name)
        module_frame = module_scope.current()
        if module_frame is None:
            raise RuntimeInvariantError("Module runner created an empty runtime scope")
        while True:
            try:
                return callback(module_scope)
            except RuntimeException as exc:
                result = self.trap.capture(exc, module_scope)
                for signal in result.signals:
                    self.bus.emit(signal)
                transfer = result.transfer
                if transfer.target == module_frame:
                    if transfer.action is RuntimeTransferAction.RETRY:
                        continue
                    raise RuntimeInvariantError(
                        "A module END transfer cannot produce a module result"
                    )
                raise RuntimeTransferInterrupt(transfer) from exc
