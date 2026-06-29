from __future__ import annotations

import pytest

from tinysoul.infra.json import JsonTypeError
from tinysoul.runtime.scope import RunFrame, RunLevel, RunScope
from tinysoul.runtime.signals import Signal, SignalBus, SignalHandlerRegistry


class _Collector:
    def __init__(self) -> None:
        self.items: list[str] = []

    def handle(self, signal: Signal) -> None:
        self.items.append(signal.name)


def test_signal_bus_keeps_order_and_clears() -> None:
    bus = SignalBus()
    scope = RunScope.of(RunFrame(RunLevel.TURN, "user"))

    first = Signal("turn.trace", "phase1", scope, {"x": 1})
    second = Signal("action.result", "phase3", scope, {"y": 2})
    bus.emit(first)
    bus.emit(second)

    assert bus.peek() == (first, second)
    assert bus.consume() == (first, second)
    assert bus.consume() == ()


def test_signal_bus_rejects_non_signal() -> None:
    bus = SignalBus()

    with pytest.raises(TypeError):
        bus.emit("bad")  # type: ignore[arg-type]


def test_signal_normalizes_payload() -> None:
    scope = RunScope.of(RunFrame(RunLevel.PROGRAM, "main"))

    signal = Signal("runtime.trace", "trap", scope, {"a": 1})

    assert signal.payload == {"a": 1}


def test_signal_rejects_non_object_payload() -> None:
    scope = RunScope.of(RunFrame(RunLevel.PROGRAM, "main"))

    with pytest.raises(JsonTypeError):
        Signal("runtime.trace", "trap", scope, ["x"])  # type: ignore[arg-type]


def test_signal_registry_dispatches_exact_and_prefix() -> None:
    exact = _Collector()
    prefix = _Collector()
    registry = SignalHandlerRegistry()
    registry.register("runtime.turn.end_requested", exact)
    registry.register_prefix("runtime.trace", prefix)

    scope = RunScope.of(RunFrame(RunLevel.TURN, "user"))
    registry.dispatch(
        [
            Signal("runtime.turn.end_requested", "runner", scope),
            Signal("runtime.trace.emitted", "trap", scope),
        ]
    )

    assert exact.items == ["runtime.turn.end_requested"]
    assert prefix.items == ["runtime.trace.emitted"]


def test_signal_registry_rejects_duplicates() -> None:
    registry = SignalHandlerRegistry()
    collector = _Collector()
    registry.register("runtime.turn.end_requested", collector)

    with pytest.raises(ValueError):
        registry.register("runtime.turn.end_requested", collector)
