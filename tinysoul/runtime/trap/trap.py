"""Runtime trap controller."""

from __future__ import annotations

from ..errors import RuntimeContractError, RuntimeInvariantError
from ..control.exception import RuntimeException
from ..control.scope import RunScope
from ..control.transfer import RuntimeTransferAction
from .snap import TrapSnap
from .handler import TrapResult
from .registry import TrapHandlerRegistry


class RuntimeTrap:
    """OS-style trap controller for runtime exceptions."""

    def __init__(self, *, registry: TrapHandlerRegistry) -> None:
        self._registry = registry

    def capture(self, exception: RuntimeException, scope: RunScope) -> TrapResult:
        snap = TrapSnap.from_exception(exception, scope)
        try:
            handler = self._registry.handler_for(snap.reason)
        except RuntimeContractError as exc:
            raise RuntimeInvariantError(
                f"No trap handler registered for runtime reason: {snap.reason}"
            ) from exc
        result = handler.handle(snap)
        if (
            result.transfer.action is RuntimeTransferAction.SUSPEND
            and result.transfer.target != snap.scope.current()
        ):
            raise RuntimeInvariantError("Suspension requires the current Turn boundary")
        if not snap.scope.contains(result.transfer.target):
            raise RuntimeInvariantError(
                "Trap handler returned a transfer target outside the captured scope: "
                f"{result.transfer.target}"
            )
        return result
