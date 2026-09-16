from __future__ import annotations

from datetime import date as CalendarDate

from tinysoul.kernel.context import ContextEngineBuilder, build_input_append_signal
from tinysoul.kernel.loop import (
    LoopControlKind,
    SIGNAL_CONTROL_REQUEST,
    build_control_request_signal,
    consume_control_requests,
    parse_control_request_signal,
)
from tinysoul.kernel.loop.context_signals import ContextSignalConsumer
from tinysoul.runtime import RunLevel, RunScope, Signal, SignalBus


def test_control_signal_roundtrip() -> None:
    scope = RunScope().push(RunLevel.AGENT, "program")
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
    scope = RunScope().push(RunLevel.AGENT, "program")
    bus = SignalBus()
    bus.emit(
        build_control_request_signal(
            LoopControlKind.STOP_TURN,
            scope=scope,
            source="test",
        )
    )
    bus.emit(Signal("loop.observation", "test", scope, {"ok": True}))
    bus.emit(Signal("context.trace.append", "test", scope, {"ok": True}))

    requests = consume_control_requests(bus)

    assert requests[0].kind is LoopControlKind.STOP_TURN
    assert tuple(signal.name for signal in bus.peek()) == (
        "loop.observation",
        "context.trace.append",
    )


async def test_context_signal_consumer_emits_and_commits_one_group() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    turn_id = context.begin_turn("initial")
    await context.open_segments(CalendarDate(2026, 7, 12))
    scope = (
        RunScope()
        .push(RunLevel.AGENT, "program")
        .push(RunLevel.TURN, turn_id)
    )
    bus = SignalBus()
    consumer = ContextSignalConsumer(context=context, bus=bus)

    results = (await consumer.emit_and_consume(
        (
            build_input_append_signal("first", scope=scope, source="test"),
            build_input_append_signal("second", scope=scope, source="test"),
        ),
        scope=scope,
    ))

    assert results == ()
    assert len(bus) == 0
    assert context.merge_pending_inputs() == 2
