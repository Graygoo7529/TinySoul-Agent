from __future__ import annotations

from queue import Queue

from tinysoul.context import SIGNAL_INPUT_APPEND
from tinysoul.loop import (
    InputRouter,
    LoopControlKind,
    LoopSettings,
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


def test_input_router_routes_initial_and_turn_inputs() -> None:
    scope = RunScope().push(RunLevel.PROGRAM, "program")
    bus = SignalBus()
    queue: Queue[str] = Queue()
    active = False
    router = InputRouter(
        settings=LoopSettings(interactive=False),
        bus=bus,
        initial_inputs=queue,
        is_turn_active=lambda: active,
        scope_provider=lambda: scope,
    )

    router.route("hello")
    assert queue.get_nowait() == "hello"

    active = True
    router.route("more context")
    assert bus.peek()[0].name == SIGNAL_INPUT_APPEND


def test_input_router_routes_control_commands() -> None:
    scope = RunScope().push(RunLevel.PROGRAM, "program")
    bus = SignalBus()
    queue: Queue[str] = Queue()
    router = InputRouter(
        settings=LoopSettings(interactive=False),
        bus=bus,
        initial_inputs=queue,
        is_turn_active=lambda: True,
        scope_provider=lambda: scope,
    )

    router.route("stop")
    router.route("exit")

    requests = consume_control_requests(bus)
    assert [request.kind for request in requests] == [
        LoopControlKind.STOP_TURN,
        LoopControlKind.EXIT_PROGRAM,
    ]


def test_input_router_routes_idle_exit_to_initial_queue() -> None:
    scope = RunScope().push(RunLevel.PROGRAM, "program")
    bus = SignalBus()
    queue: Queue[str] = Queue()
    router = InputRouter(
        settings=LoopSettings(interactive=False),
        bus=bus,
        initial_inputs=queue,
        is_turn_active=lambda: False,
        scope_provider=lambda: scope,
    )

    router.route("exit")

    assert queue.get_nowait() == "exit"
    assert len(bus) == 0
