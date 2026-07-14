from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from tinysoul.app import MaintenanceSchedule, SchedulerSettings
from tinysoul.loop import BusinessDay, ProgramInputKind, ProgramWorkMode


ZONE = ZoneInfo("Asia/Shanghai")


def test_maintenance_schedule_emits_daily_home_and_memory_in_order() -> None:
    schedule = MaintenanceSchedule(
        SchedulerSettings(),
        now=datetime(2026, 7, 14, 23, 59, tzinfo=ZONE),
    )

    daily = schedule.due(datetime(2026, 7, 15, 0, 0, tzinfo=ZONE))
    home = schedule.due(datetime(2026, 7, 15, 0, 5, tzinfo=ZONE))
    memory = schedule.due(datetime(2026, 7, 15, 0, 15, tzinfo=ZONE))

    assert [event.kind for event in daily] == [ProgramInputKind.DAILY_ROLLOVER]
    assert [event.kind for event in home] == [ProgramInputKind.HOME_MAINTENANCE]
    assert home[0].mode is ProgramWorkMode.AUTOMATIC
    assert [event.kind for event in memory] == [ProgramInputKind.MEMORY_MAINTENANCE]
    assert memory[0].mode is ProgramWorkMode.AUTOMATIC
    assert memory[0].target_day == BusinessDay.parse("2026-07-14")


def test_maintenance_schedule_does_not_catch_up_before_process_start() -> None:
    now = datetime(2026, 7, 15, 0, 20, tzinfo=ZONE)
    schedule = MaintenanceSchedule(SchedulerSettings(), now=now)

    assert schedule.due(now) == ()


def test_maintenance_schedule_collapses_multi_day_sleep_to_current_day() -> None:
    schedule = MaintenanceSchedule(
        SchedulerSettings(),
        now=datetime(2026, 7, 14, 23, 0, tzinfo=ZONE),
    )

    events = schedule.due(datetime(2026, 7, 16, 0, 20, tzinfo=ZONE))

    assert [event.kind for event in events] == [
        ProgramInputKind.DAILY_ROLLOVER,
        ProgramInputKind.HOME_MAINTENANCE,
        ProgramInputKind.MEMORY_MAINTENANCE,
    ]
    assert events[2].target_day == BusinessDay.parse("2026-07-15")
    assert schedule.due(datetime(2026, 7, 16, 0, 21, tzinfo=ZONE)) == ()
