from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from tinysoul.runtime.errors import RuntimeInvariantError
from tinysoul.runtime.exception import (
    CONTEXT_COMPRESSION_REQUIRED,
    HOME_RUNTIME_COPY_REQUIRED,
    RUNTIME_CYCLE_END,
    RUNTIME_PROGRAM_END,
    RUNTIME_STARTUP_FAILED,
    RUNTIME_TURN_END,
    RuntimeException,
)
from tinysoul.runtime.scope import RunFrame, RunLevel, RunScope
from tinysoul.runtime.signals import Signal
from tinysoul.runtime.trap import (
    RuntimeTrap,
    TrapHandlerRegistry,
    TrapResult,
    TrapSnap,
)
from tinysoul.runtime.transfer import RuntimeTransfer


@dataclass
class _Handler:
    transfer: RuntimeTransfer
    emitted: tuple[Signal, ...] = ()
    snaps: list[TrapSnap] = field(default_factory=list)

    def handle(self, snap: TrapSnap) -> TrapResult:
        self.snaps.append(snap)
        return TrapResult(transfer=self.transfer, signals=self.emitted)


def test_trap_captures_snap_and_dispatches_handler() -> None:
    scope = RunScope.of(
        RunFrame(RunLevel.PROGRAM, "main"),
        RunFrame(RunLevel.TURN, "user"),
        RunFrame(RunLevel.CYCLE, "1"),
        RunFrame(RunLevel.PHASE, "phase1"),
    )
    current = scope.current()
    assert current is not None
    handler = _Handler(transfer=RuntimeTransfer.retry(current))
    registry = TrapHandlerRegistry()
    registry.register(CONTEXT_COMPRESSION_REQUIRED, handler)
    trap = RuntimeTrap(registry=registry)

    result = trap.capture(
        RuntimeException(
            reason=CONTEXT_COMPRESSION_REQUIRED,
            message="compress",
            payload={"limit": 100},
        ),
        scope,
    )

    assert result.transfer == RuntimeTransfer.retry(current)
    assert handler.snaps[0].reason == CONTEXT_COMPRESSION_REQUIRED
    assert handler.snaps[0].scope == scope
    assert handler.snaps[0].payload == {"limit": 100}


def test_trap_registry_supports_prefix_handlers() -> None:
    scope = RunScope.of(RunFrame(RunLevel.PROGRAM, "main"))
    current = scope.current()
    assert current is not None
    handler = _Handler(transfer=RuntimeTransfer.end(current))
    registry = TrapHandlerRegistry()
    registry.register_prefix("runtime", handler)
    trap = RuntimeTrap(registry=registry)

    result = trap.capture(
        RuntimeException(
            reason=RUNTIME_PROGRAM_END,
            message="exit",
            payload={},
        ),
        scope,
    )

    assert result.transfer == RuntimeTransfer.end(current)
    assert handler.snaps[0].reason == RUNTIME_PROGRAM_END


def test_trap_handler_can_emit_signals() -> None:
    scope = RunScope.of(RunFrame(RunLevel.TURN, "user"))
    signal = Signal("turn.trace.append_requested", "trap", scope, {"note": "x"})
    current = scope.current()
    assert current is not None
    handler = _Handler(
        transfer=RuntimeTransfer.end(current),
        emitted=(signal,),
    )
    registry = TrapHandlerRegistry()
    registry.register(RUNTIME_TURN_END, handler)
    trap = RuntimeTrap(registry=registry)

    result = trap.capture(
        RuntimeException(
            reason=RUNTIME_TURN_END,
            message="stop",
            payload={},
        ),
        scope,
    )

    assert result.signals == (signal,)


def test_trap_unknown_reason_raises_runtime_invariant_error() -> None:
    scope = RunScope.of(RunFrame(RunLevel.PROGRAM, "main"))
    trap = RuntimeTrap(registry=TrapHandlerRegistry())

    with pytest.raises(RuntimeInvariantError) as raised:
        trap.capture(
            RuntimeException(reason=HOME_RUNTIME_COPY_REQUIRED, message="copy", payload={}),
            scope,
        )

    assert "No trap handler registered" in str(raised.value)


def test_trap_rejects_transfer_target_outside_captured_scope() -> None:
    scope = RunScope.of(RunFrame(RunLevel.PROGRAM, "main"))
    handler = _Handler(
        transfer=RuntimeTransfer.end(RunFrame(RunLevel.TURN, "foreign"))
    )
    registry = TrapHandlerRegistry()
    registry.register(RUNTIME_TURN_END, handler)

    with pytest.raises(RuntimeInvariantError, match="outside the captured scope"):
        RuntimeTrap(registry=registry).capture(
            RuntimeException(
                reason=RUNTIME_TURN_END,
                message="stop",
            ),
            scope,
        )


def test_trap_registry_uses_explicit_fallback_for_unknown_reason() -> None:
    scope = RunScope.of(RunFrame(RunLevel.PROGRAM, "main"))
    current = scope.current()
    assert current is not None
    fallback = _Handler(transfer=RuntimeTransfer.end(current))
    registry = TrapHandlerRegistry()
    registry.register_fallback(fallback)
    trap = RuntimeTrap(registry=registry)

    result = trap.capture(
        RuntimeException(reason="module.unhandled", message="failed", payload={}),
        scope,
    )

    assert result.transfer == RuntimeTransfer.end(current)
    assert fallback.snaps[0].reason == "module.unhandled"


def test_common_reasons_are_constants() -> None:
    assert RUNTIME_STARTUP_FAILED == "runtime.startup_failed"
    assert RUNTIME_CYCLE_END == "runtime.cycle_end"
