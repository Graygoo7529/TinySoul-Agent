from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from tinysoul.plugins.reflection import (
    ReflectionSchedule,
    ReflectionScheduleSettings,
    ReflectionScope,
    ReflectionTrigger,
)
from tinysoul.plugins.reflection.schedule import ReflectionScheduler
from tinysoul.infra.time import CalendarDay
from tinysoul.runtime.events import EnvironmentEvent, EventReceipt
from tinysoul.environment.sources.scheduler import DeadlineTimer
from collections.abc import Awaitable, Callable

ZONE = ZoneInfo("Asia/Shanghai")


def test_schedule_emits_one_scheduled_daily_request_when_due() -> None:
    schedule = ReflectionSchedule(
        ReflectionScheduleSettings(daily_time=time(0, 15)),
        now=datetime(2026, 7, 15, 0, 10, tzinfo=ZONE),
    )
    assert schedule.due(datetime(2026, 7, 15, 0, 14, tzinfo=ZONE)) == ()

    requests = schedule.due(datetime(2026, 7, 15, 0, 15, tzinfo=ZONE))

    assert len(requests) == 1
    assert requests[0].scope is ReflectionScope.DAILY
    assert requests[0].trigger is ReflectionTrigger.SCHEDULED
    assert schedule.due(datetime(2026, 7, 15, 12, 0, tzinfo=ZONE)) == ()


def test_schedule_started_after_due_does_not_catch_up_startup_work() -> None:
    now = datetime(2026, 7, 15, 9, 0, tzinfo=ZONE)
    schedule = ReflectionSchedule(ReflectionScheduleSettings(), now=now)

    assert schedule.due(now) == ()
    assert schedule.due(now + timedelta(minutes=1)) == ()


def test_schedule_collapses_multi_day_sleep_to_one_request() -> None:
    start = datetime(2026, 7, 15, 0, 0, tzinfo=ZONE)
    schedule = ReflectionSchedule(ReflectionScheduleSettings(), now=start)

    requests = schedule.due(start + timedelta(days=3, minutes=20))

    assert len(requests) == 1
    assert requests[0].scope is ReflectionScope.DAILY


async def test_trigger_retries_the_same_due_day_after_midnight() -> None:
    class Clock:
        value = datetime(2026, 9, 20, 0, 0, tzinfo=ZONE)

        def now(self) -> datetime:
            return self.value

        def today(self) -> CalendarDay:
            return CalendarDay(self.value.date())

    class Timer:
        async def start(self, tick: Callable[[], Awaitable[float]]) -> None:
            pass

        async def stop(self) -> None:
            pass

    clock = Clock()
    requests = []
    events: list[EnvironmentEvent] = []

    async def submit(request) -> bool:
        requests.append(request)
        return len(requests) > 1

    async def publish(event: EnvironmentEvent) -> EventReceipt:
        events.append(event)
        return EventReceipt(1, event.event_id, False)

    source = ReflectionScheduler(ReflectionScheduleSettings(daily_time=time(0, 15)),
                                 clock=clock, timer=Timer(), submit=submit)
    await source.start(publish)
    clock.value = datetime(2026, 9, 20, 0, 15, tzinfo=ZONE)
    assert await source.tick() <= 1
    clock.value = datetime(2026, 9, 21, 0, 10, tzinfo=ZONE)
    await source.tick()
    assert requests[0] is requests[1]
    assert requests[1].scheduled_day == CalendarDay.parse("2026-09-20")
    assert len(events) == 1 and events[0].topic == "reflection.due"
    await source.stop()


async def test_deadline_timer_stops_without_waiting_for_next_due_time() -> None:
    import asyncio
    called = asyncio.Event()

    async def tick() -> float:
        called.set()
        return 86400

    timer = DeadlineTimer()
    await timer.start(tick)
    await asyncio.wait_for(called.wait(), 1)
    await asyncio.wait_for(timer.stop(), 1)
