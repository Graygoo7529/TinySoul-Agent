from __future__ import annotations

from typing import cast

import pytest

from tinysoul.infra.json import JsonObject
from tinysoul.runtime.errors import RuntimeContractError
from tinysoul.runtime.scope import RunFrame, RunLevel, RunScope
from tinysoul.runtime.signals import Signal, SignalBus


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


def test_signal_bus_consumes_exact_name_only() -> None:
    bus = SignalBus()
    scope = RunScope.of(RunFrame(RunLevel.TURN, "user"))
    first = Signal("loop.control.request", "test", scope)
    second = Signal("loop.observation", "test", scope)
    third = Signal("context.trace.append", "test", scope)
    bus.emit(first)
    bus.emit(second)
    bus.emit(third)

    assert bus.consume_name("loop.control.request") == (first,)
    assert bus.peek() == (second, third)


def test_signal_bus_rejects_non_signal() -> None:
    bus = SignalBus()

    with pytest.raises(RuntimeContractError):
        bus.emit(cast(Signal, "bad"))


def test_signal_normalizes_payload() -> None:
    scope = RunScope.of(RunFrame(RunLevel.PROGRAM, "main"))

    signal = Signal("runtime.trace", "trap", scope, {"a": 1})

    assert signal.payload == {"a": 1}


def test_signal_rejects_non_object_payload() -> None:
    scope = RunScope.of(RunFrame(RunLevel.PROGRAM, "main"))

    with pytest.raises(RuntimeContractError):
        Signal("runtime.trace", "trap", scope, cast(JsonObject, ["x"]))
