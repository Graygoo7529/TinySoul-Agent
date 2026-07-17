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


def test_signal_bus_matching_wait_is_non_consuming_and_cursor_bound() -> None:
    bus = SignalBus()
    scope = RunScope.of(RunFrame(RunLevel.TURN, "turn_1"))
    first = Signal("workspace.sync", "test", scope)
    second = Signal("context.input.append", "test", scope, {"text": "more"})
    bus.emit(first)
    watch = bus.watch()
    bus.emit(second)
    assert bus.consume_name("context.input.append") == (second,)

    matched = watch.wait_for_matching(
        lambda signal: signal.name == "context.input.append",
        0,
    )

    assert matched is second
    assert bus.peek() == (first,)
    assert watch.wait_for_matching(lambda _signal: True, 0) is None
    watch.close()


def test_signal_normalizes_payload() -> None:
    scope = RunScope.of(RunFrame(RunLevel.PROGRAM, "main"))

    signal = Signal("runtime.trace", "trap", scope, {"a": 1})

    assert signal.payload == {"a": 1}


def test_signal_rejects_non_object_payload() -> None:
    scope = RunScope.of(RunFrame(RunLevel.PROGRAM, "main"))

    with pytest.raises(RuntimeContractError):
        Signal("runtime.trace", "trap", scope, cast(JsonObject, ["x"]))
