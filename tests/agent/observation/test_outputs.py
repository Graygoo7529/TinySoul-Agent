from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from tinysoul.agent.observation.outputs import ObservationRoute
from tinysoul.agent.observation.outputs import ObservationRouter
from tinysoul.runtime import ObservationEvent, ObservationLevel


@dataclass
class _RecordingSink:
    events: list[ObservationEvent] = field(default_factory=list)

    def write(self, event: ObservationEvent) -> None:
        self.events.append(event)


@dataclass
class _FailingSink:
    calls: int = 0

    def write(self, event: ObservationEvent) -> None:
        self.calls += 1
        raise OSError("closed output")


@pytest.mark.parametrize(
    ("mode", "expected"),
    ((ObservationLevel.NORMAL, ("normal",)),
     (ObservationLevel.VERBOSE, ("normal", "verbose")),
     (ObservationLevel.MODEL, ("normal", "verbose", "model"))),
)
def test_observation_router_filters_each_route_at_its_declared_level(
    mode: ObservationLevel, expected: tuple[str, ...],
) -> None:
    sink = _RecordingSink()
    router = ObservationRouter(routes=(ObservationRoute(sink, mode),))

    for level in ObservationLevel:
        router.emit(
            ObservationEvent(
                name=level.value,
                level=level,
                source="test",
            )
        )

    assert tuple(event.name for event in sink.events) == expected


def test_observation_router_isolates_and_reports_sink_failure() -> None:
    failing = _FailingSink()
    healthy = _RecordingSink()
    router = ObservationRouter(routes=tuple(
        ObservationRoute(sink, ObservationLevel.NORMAL) for sink in (failing, healthy)
    ))
    event = ObservationEvent(
        name="turn.output",
        level=ObservationLevel.NORMAL,
        source="loop.turn",
        payload={"text": "answer"},
    )

    router.emit(event)
    router.emit(event)

    assert failing.calls == 1
    assert healthy.events == [event, event]
    assert len(router.failures) == 1
    assert router.failures[0].error_type == "OSError"


def test_observation_router_filters_each_sink_independently() -> None:
    normal = _RecordingSink()
    model = _RecordingSink()
    router = ObservationRouter(
        routes=(
            ObservationRoute(normal, ObservationLevel.NORMAL),
            ObservationRoute(model, ObservationLevel.MODEL),
        ),
    )

    for level in ObservationLevel:
        router.emit(ObservationEvent(name=level.value, level=level, source="test"))

    assert [event.name for event in normal.events] == ["normal"]
    assert [event.name for event in model.events] == [
        "normal",
        "verbose",
        "model",
    ]


def test_removing_route_keeps_failure_isolation_on_the_same_sink() -> None:
    first, failing, last = _RecordingSink(), _FailingSink(), _RecordingSink()
    routes = tuple(ObservationRoute(sink, ObservationLevel.NORMAL) for sink in (first, failing, last))
    router = ObservationRouter(routes=routes)
    event = ObservationEvent(name="test", source="test", level=ObservationLevel.NORMAL)
    router.emit(event)
    router.remove_route(routes[0])
    router.emit(event)
    assert failing.calls == 1
    assert first.events == [event]
    assert last.events == [event, event]
