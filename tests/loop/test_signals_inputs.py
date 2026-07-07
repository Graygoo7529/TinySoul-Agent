from __future__ import annotations

from tinysoul.loop import (
    LoopControlKind,
    SIGNAL_CONTROL_REQUEST,
    build_control_request_signal,
    consume_control_requests,
    parse_control_request_signal,
)
from tinysoul.runtime import RunLevel, RunScope, SignalBus


def test_control_signal_roundtrip() -> None:
    scope = RunScope().push(RunLevel.PROGRAM, "program")
    signal = build_control_request_signal(
        LoopControlKind.EXIT_PROGRAM,
        scope=scope,
        source="test",
        text="exit",
    )

    parsed = parse_control_request_signal(signal)

    assert signal.name == SIGNAL_CONTROL_REQUEST
    assert parsed.kind is LoopControlKind.EXIT_PROGRAM
    assert parsed.text == "exit"


def test_consume_control_requests_leaves_non_loop_signals() -> None:
    scope = RunScope().push(RunLevel.PROGRAM, "program")
    bus = SignalBus()
    bus.emit(
        build_control_request_signal(
            LoopControlKind.STOP_TURN,
            scope=scope,
            source="test",
        )
    )

    requests = consume_control_requests(bus)

    assert requests[0].kind is LoopControlKind.STOP_TURN
    assert len(bus) == 0
