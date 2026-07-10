"""Loop integration for transactional Context signal consumption."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.context import ContextEngine, ControlResult
from tinysoul.context.errors import ContextError
from tinysoul.runtime import RunScope, RuntimeModuleRunner, SignalBus
from tinysoul.runtime.bridge import RuntimeContextBridge


@dataclass(frozen=True)
class ContextSignalConsumer:
    """Commit one captured Context batch under a replayable Module frame."""

    context: ContextEngine
    bus: SignalBus
    module_runner: RuntimeModuleRunner | None = None
    runtime_bridge: RuntimeContextBridge = RuntimeContextBridge()

    def consume(self, *, scope: RunScope) -> tuple[ControlResult, ...]:
        try:
            batch = self.context.take_signal_batch(self.bus)
        except ContextError as exc:
            raise self.runtime_bridge.from_context_error(exc) from exc
        if not batch.signals:
            return ()

        def commit() -> tuple[ControlResult, ...]:
            try:
                return self.context.consume_signal_batch(batch)
            except ContextError as exc:
                raise self.runtime_bridge.from_context_error(exc) from exc

        if self.module_runner is None:
            return commit()
        return self.module_runner.run(
            scope=scope,
            name="context.consume_signals",
            callback=lambda _module_scope: commit(),
        )
