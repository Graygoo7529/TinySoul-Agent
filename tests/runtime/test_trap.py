from __future__ import annotations

from dataclasses import dataclass, field

from tinysoul.runtime.exception import (
    CONTEXT_COMPRESSION_REQUIRED,
    HOME_RUNTIME_COPY_REQUIRED,
    PROGRAM_END_REQUESTED,
    RUNTIME_CYCLE_END_REQUESTED,
    RUNTIME_STARTUP_FAILED,
    RUNTIME_TURN_END_REQUESTED,
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
    handler = _Handler(transfer=RuntimeTransfer.retry(scope.current()))
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

    assert result.transfer == RuntimeTransfer.retry(scope.current())
    assert handler.snaps[0].reason == CONTEXT_COMPRESSION_REQUIRED
    assert handler.snaps[0].scope == scope
    assert handler.snaps[0].payload == {"limit": 100}


def test_trap_registry_supports_prefix_handlers() -> None:
    scope = RunScope.of(RunFrame(RunLevel.PROGRAM, "main"))
    handler = _Handler(transfer=RuntimeTransfer.end(scope.current()))
    registry = TrapHandlerRegistry()
    registry.register_prefix("runtime", handler)
    trap = RuntimeTrap(registry=registry)

    result = trap.capture(
        RuntimeException(
            reason=PROGRAM_END_REQUESTED,
            message="exit",
            payload={},
        ),
        scope,
    )

    assert result.transfer == RuntimeTransfer.end(scope.current())
    assert handler.snaps[0].reason == PROGRAM_END_REQUESTED


def test_trap_handler_can_emit_signals() -> None:
    scope = RunScope.of(RunFrame(RunLevel.TURN, "user"))
    signal = Signal("turn.trace.append_requested", "trap", scope, {"note": "x"})
    handler = _Handler(
        transfer=RuntimeTransfer.end(scope.current()),
        emitted=(signal,),
    )
    registry = TrapHandlerRegistry()
    registry.register(RUNTIME_TURN_END_REQUESTED, handler)
    trap = RuntimeTrap(registry=registry)

    result = trap.capture(
        RuntimeException(
            reason=RUNTIME_TURN_END_REQUESTED,
            message="stop",
            payload={},
        ),
        scope,
    )

    assert result.signals == (signal,)


def test_trap_unknown_reason_raises_lookup_error() -> None:
    scope = RunScope.of(RunFrame(RunLevel.PROGRAM, "main"))
    trap = RuntimeTrap(registry=TrapHandlerRegistry())

    try:
        trap.capture(
            RuntimeException(reason=HOME_RUNTIME_COPY_REQUIRED, message="copy", payload={}),
            scope,
        )
    except LookupError as exc:
        assert "Unknown trap reason" in str(exc)
    else:
        raise AssertionError("Expected LookupError")


def test_common_reasons_are_constants() -> None:
    assert RUNTIME_STARTUP_FAILED == "runtime.startup_failed"
    assert RUNTIME_CYCLE_END_REQUESTED == "runtime.cycle_end_requested"
