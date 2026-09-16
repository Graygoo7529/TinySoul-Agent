"""Loop integration for transactional Context signal consumption."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.kernel.context import ContextEngine, ContextSignalBatch, ControlResult
from tinysoul.kernel.context.signals import SIGNAL_NAMESPACE
from tinysoul.kernel.context.errors import ContextError
from tinysoul.runtime import RunLevel, RunScope, RuntimeModuleRunner, Signal, SignalBus
from tinysoul.kernel.context.runtime_bridge import RuntimeContextBridge
from .errors import LoopInvariantError
from .runtime_bridge import RuntimeLoopBridge


@dataclass(frozen=True)
class ContextSignalConsumer:
    """Commit one captured Context batch under a replayable Module frame."""

    context: ContextEngine
    bus: SignalBus
    module_runner: RuntimeModuleRunner | None = None
    runtime_bridge: RuntimeContextBridge = RuntimeContextBridge()

    async def consume_recovery(self, signals: tuple[Signal, ...], scope: RunScope) -> None:
        """Install the Trap's own updates before retry, without draining new input."""
        context_signals: list[Signal] = []
        for signal in signals:
            if signal.name.startswith(f"{SIGNAL_NAMESPACE}."):
                context_signals.append(signal)
            else:
                self.bus.emit(signal)
        if not context_signals:
            return
        turn = scope.nearest(RunLevel.TURN)
        if turn is None:
            raise RuntimeLoopBridge().from_loop_error(
                LoopInvariantError("Recovery Context updates require a Turn frame")
            )
        try:
            results = await self.context.consume_signal_batch(
                ContextSignalBatch(turn_id=turn.name, signals=tuple(context_signals))
            )
        except ContextError as exc:
            raise self.runtime_bridge.from_context_error(exc) from exc
        if results:
            raise RuntimeLoopBridge().from_loop_error(
                LoopInvariantError("Context rejected an internal recovery update")
            )

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

        return await self.consume_batch(batch, scope=scope)

    async def consume_batch(
        self, batch: ContextSignalBatch, *, scope: RunScope,
    ) -> tuple[ControlResult, ...]:
        """Retry this exact batch without capturing unrelated later arrivals."""

        async def commit(_module_scope: RunScope) -> tuple[ControlResult, ...]:
            try:
                return await self.context.consume_signal_batch(batch)
            except ContextError as exc:
                raise self.runtime_bridge.from_context_error(exc) from exc

        if self.module_runner is None:
            return await commit(scope)
        return await self.module_runner.run(
            scope=scope,
            name="context.consume_signals",
            callback=commit,
        )
