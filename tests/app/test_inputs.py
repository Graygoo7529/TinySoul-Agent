from __future__ import annotations

from queue import Queue

from tinysoul.app import (
    InputCommandParser,
    InputDispatcher,
    InputEvent,
    InputIntentKind,
)
from tinysoul.context import SIGNAL_INPUT_APPEND
from tinysoul.loop import (
    BusinessDay,
    LoopControlKind,
    ProgramWorkMode,
    SIGNAL_CONTROL_REQUEST,
    consume_control_requests,
)
from tinysoul.loop.program import ProgramInputEvent, ProgramInputKind
from tinysoul.runtime import RunLevel, RunScope, SignalBus


def test_input_command_parser_classifies_by_turn_state() -> None:
    parser = InputCommandParser()

    assert parser.parse(InputEvent("hello"), turn_active=False).kind is InputIntentKind.START_TURN
    assert parser.parse(InputEvent("hello"), turn_active=True).kind is InputIntentKind.APPEND_INPUT
    assert parser.parse(InputEvent("stop"), turn_active=True).kind is InputIntentKind.STOP_TURN
    assert parser.parse(InputEvent("exit"), turn_active=False).kind is InputIntentKind.EXIT_PROGRAM
    assert parser.parse(InputEvent("   "), turn_active=False).kind is InputIntentKind.IGNORE


def test_input_command_parser_classifies_maintenance_commands() -> None:
    parser = InputCommandParser()

    home = parser.parse(InputEvent("/maintenance home"), turn_active=True)
    memory = parser.parse(InputEvent("/maintenance memory"), turn_active=False)
    dated = parser.parse(
        InputEvent("/maintenance memory 2026-07-12"),
        turn_active=True,
    )
    invalid = parser.parse(
        InputEvent("/maintenance memory yesterday"),
        turn_active=False,
    )

    assert home.kind is InputIntentKind.HOME_MAINTENANCE
    assert memory.kind is InputIntentKind.MEMORY_MAINTENANCE
    assert memory.target_day is None
    assert dated.kind is InputIntentKind.MEMORY_MAINTENANCE
    assert dated.target_day == BusinessDay.parse("2026-07-12")
    assert invalid.kind is InputIntentKind.REJECTED
    assert "YYYY-MM-DD" in invalid.error


def test_input_dispatcher_routes_initial_and_turn_inputs() -> None:
    scope = (
        RunScope()
        .push(RunLevel.PROGRAM, "program")
        .push(RunLevel.TURN, "turn_1")
    )
    bus = SignalBus()
    queue: Queue[ProgramInputEvent] = Queue()
    active_scope: RunScope | None = None
    dispatcher = InputDispatcher(
        parser=InputCommandParser(),
        bus=bus,
        program_inputs=queue,
        active_turn_scope=lambda: active_scope,
    )

    dispatcher.submit(InputEvent("hello"))
    event = queue.get_nowait()
    assert event.kind is ProgramInputKind.START_TURN
    assert event.text == "hello"

    active_scope = scope
    dispatcher.submit(InputEvent("more context"))
    assert bus.peek()[0].name == SIGNAL_INPUT_APPEND
    turn_frame = bus.peek()[0].scope.nearest(RunLevel.TURN)
    assert turn_frame is not None
    assert turn_frame.name == "turn_1"


def test_input_dispatcher_routes_active_control_commands() -> None:
    scope = (
        RunScope()
        .push(RunLevel.PROGRAM, "program")
        .push(RunLevel.TURN, "turn_1")
    )
    bus = SignalBus()
    queue: Queue[ProgramInputEvent] = Queue()
    dispatcher = InputDispatcher(
        parser=InputCommandParser(),
        bus=bus,
        program_inputs=queue,
        active_turn_scope=lambda: scope,
    )

    dispatcher.submit(InputEvent("stop"))
    dispatcher.submit(InputEvent("exit"))

    assert [signal.name for signal in bus.peek()] == [
        SIGNAL_CONTROL_REQUEST,
        SIGNAL_CONTROL_REQUEST,
    ]
    requests = consume_control_requests(bus)
    assert [request.kind for request in requests] == [
        LoopControlKind.STOP_TURN,
        LoopControlKind.EXIT_PROGRAM,
    ]
    assert queue.empty()


def test_input_dispatcher_routes_active_maintenance_to_program_queue() -> None:
    scope = (
        RunScope()
        .push(RunLevel.PROGRAM, "program")
        .push(RunLevel.TURN, "turn_1")
    )
    bus = SignalBus()
    queue: Queue[ProgramInputEvent] = Queue()
    dispatcher = InputDispatcher(
        parser=InputCommandParser(),
        bus=bus,
        program_inputs=queue,
        active_turn_scope=lambda: scope,
    )

    dispatcher.submit(InputEvent("/maintenance home", source="terminal"))
    dispatcher.submit(
        InputEvent("/maintenance memory 2026-07-10", source="terminal")
    )

    home = queue.get_nowait()
    memory = queue.get_nowait()
    assert home.kind is ProgramInputKind.HOME_MAINTENANCE
    assert home.mode is ProgramWorkMode.MANUAL
    assert memory.kind is ProgramInputKind.MEMORY_MAINTENANCE
    assert memory.mode is ProgramWorkMode.MANUAL
    assert memory.target_day == BusinessDay.parse("2026-07-10")
    assert len(bus) == 0


def test_input_dispatcher_routes_idle_exit_to_program_queue() -> None:
    bus = SignalBus()
    queue: Queue[ProgramInputEvent] = Queue()
    dispatcher = InputDispatcher(
        parser=InputCommandParser(),
        bus=bus,
        program_inputs=queue,
        active_turn_scope=lambda: None,
    )

    dispatcher.submit(InputEvent("exit", source="test"))

    event = queue.get_nowait()
    assert event.kind is ProgramInputKind.EXIT_PROGRAM
    assert event.text == "exit"
    assert event.source == "test"
    assert len(bus) == 0
