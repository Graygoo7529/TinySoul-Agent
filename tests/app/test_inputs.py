from __future__ import annotations

from queue import Queue

from tinysoul.app.inputs import (
    InputCommandParser,
    InputDispatcher,
    InputEvent,
    InputIntentKind,
)
from tinysoul.app.requests import AppRequest, ExitRequest, UserTurnRequest
from tinysoul.context import SIGNAL_INPUT_APPEND
from tinysoul.loop import (
    SIGNAL_CONTROL_REQUEST,
    LoopControlKind,
    consume_control_requests,
)
from tinysoul.maintenance import (
    BusinessDay,
    MaintenanceRequest,
    MaintenanceScope,
    MaintenanceTrigger,
)
from tinysoul.runtime import RunLevel, RunScope, SignalBus


def test_input_parser_separates_user_and_active_turn_input() -> None:
    parser = InputCommandParser()
    assert parser.parse(InputEvent("hello"), turn_active=False).kind is (
        InputIntentKind.USER_TURN
    )
    assert parser.parse(InputEvent("more"), turn_active=True).kind is (
        InputIntentKind.APPEND_INPUT
    )


def test_input_parser_supports_all_maintenance_scopes_and_rebuild() -> None:
    parser = InputCommandParser()
    daily = parser.parse(InputEvent("/maintenance"), turn_active=False)
    home = parser.parse(InputEvent("/maintenance home"), turn_active=False)
    memory = parser.parse(
        InputEvent("/maintenance memory --rebuild 2026-07-12"),
        turn_active=False,
    )
    invalid = parser.parse(
        InputEvent("/maintenance memory tomorrow"),
        turn_active=False,
    )

    assert daily.maintenance_scope is MaintenanceScope.DAILY
    assert home.maintenance_scope is MaintenanceScope.HOME
    assert memory.maintenance_scope is MaintenanceScope.MEMORY
    assert memory.target_day == BusinessDay.parse("2026-07-12")
    assert memory.rebuild_memory is True
    assert invalid.kind is InputIntentKind.REJECTED


def test_dispatcher_routes_user_input_to_queue_or_active_turn_signal() -> None:
    bus = SignalBus()
    queue: Queue[AppRequest] = Queue()
    active_scope: RunScope | None = None
    dispatcher = InputDispatcher(
        parser=InputCommandParser(),
        bus=bus,
        program_inputs=queue,
        active_turn_scope=lambda: active_scope,
    )
    dispatcher.submit(InputEvent("hello"))
    request = queue.get_nowait()
    assert isinstance(request, UserTurnRequest)
    assert request.text == "hello"

    active_scope = _turn_scope()
    dispatcher.submit(InputEvent("more context"))
    assert bus.peek()[0].name == SIGNAL_INPUT_APPEND


def test_dispatcher_queues_manual_maintenance_even_during_user_turn() -> None:
    bus = SignalBus()
    queue: Queue[AppRequest] = Queue()
    dispatcher = InputDispatcher(
        parser=InputCommandParser(),
        bus=bus,
        program_inputs=queue,
        active_turn_scope=_turn_scope,
    )
    dispatcher.submit(
        InputEvent("/maintenance memory 2026-07-10 --rebuild", source="terminal")
    )

    request = queue.get_nowait()
    assert isinstance(request, MaintenanceRequest)
    assert request.scope is MaintenanceScope.MEMORY
    assert request.trigger is MaintenanceTrigger.MANUAL
    assert request.target_day == BusinessDay.parse("2026-07-10")
    assert request.rebuild_memory is True
    assert len(bus) == 0


def test_dispatcher_routes_active_controls_and_idle_exit() -> None:
    bus = SignalBus()
    queue: Queue[AppRequest] = Queue()
    active: RunScope | None = _turn_scope()
    dispatcher = InputDispatcher(
        parser=InputCommandParser(),
        bus=bus,
        program_inputs=queue,
        active_turn_scope=lambda: active,
    )
    dispatcher.submit(InputEvent("stop"))
    dispatcher.submit(InputEvent("exit"))
    assert [signal.name for signal in bus.peek()] == [
        SIGNAL_CONTROL_REQUEST,
        SIGNAL_CONTROL_REQUEST,
    ]
    assert [item.kind for item in consume_control_requests(bus)] == [
        LoopControlKind.STOP_TURN,
        LoopControlKind.EXIT_PROGRAM,
    ]

    active = None
    dispatcher.submit(InputEvent("exit", source="test"))
    request = queue.get_nowait()
    assert isinstance(request, ExitRequest)
    assert request.source == "test"


def _turn_scope() -> RunScope:
    return (
        RunScope()
        .push(RunLevel.PROGRAM, "program")
        .push(RunLevel.TURN, "turn_1")
    )
