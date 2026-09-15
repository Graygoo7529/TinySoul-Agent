"""Loop integration for transactional Context signal consumption."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.context import ContextEngine, ControlResult
from tinysoul.context.errors import ContextError
from tinysoul.runtime import RunScope, RuntimeModuleRunner, Signal, SignalBus
from tinysoul.context.runtime_bridge import RuntimeContextBridge


@dataclass(frozen=True)
class ContextSignalConsumer:
    """Commit one captured Context batch under a replayable Module frame."""

    context: ContextEngine
    bus: SignalBus
    module_runner: RuntimeModuleRunner | None = None
    runtime_bridge: RuntimeContextBridge = RuntimeContextBridge()

    async def emit_and_consume(
        self,
        signals: tuple[Signal, ...],
        *,
        scope: RunScope,
    ) -> tuple[ControlResult, ...]:
        """Emit related Context signals and commit them as one captured batch."""

        for signal in signals:
            self.bus.emit(signal)
        return await self.consume(scope=scope)

    async def consume(self, *, scope: RunScope) -> tuple[ControlResult, ...]:
        try:
            batch = self.context.take_signal_batch(self.bus)
        except ContextError as exc:
            raise self.runtime_bridge.from_context_error(exc) from exc
        if not batch.signals:
            return ()

        async def commit(_module_scope: RunScope) -> tuple[ControlResult, ...]:
            try:
                return tuple(self.context.consume_signal_batch(batch))
            except ContextError as exc:
                raise self.runtime_bridge.from_context_error(exc) from exc

        if self.module_runner is None:
            return await commit(scope)
        return await self.module_runner.run(
            scope=scope,
            name="context.consume_signals",
            callback=commit,
        )
