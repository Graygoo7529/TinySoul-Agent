from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from tinysoul.maintenance import (
    MaintenanceSchedule,
    MaintenanceScheduleSettings,
    MaintenanceScope,
    MaintenanceTrigger,
)


ZONE = ZoneInfo("Asia/Shanghai")


def test_schedule_emits_one_scheduled_daily_request_when_due() -> None:
    schedule = MaintenanceSchedule(
        MaintenanceScheduleSettings(daily_time=time(0, 15)),
        now=datetime(2026, 7, 15, 0, 10, tzinfo=ZONE),
    )
    assert schedule.due(datetime(2026, 7, 15, 0, 14, tzinfo=ZONE)) == ()

    requests = schedule.due(datetime(2026, 7, 15, 0, 15, tzinfo=ZONE))

    assert len(requests) == 1
    assert requests[0].scope is MaintenanceScope.DAILY
    assert requests[0].trigger is MaintenanceTrigger.SCHEDULED
    assert schedule.due(datetime(2026, 7, 15, 12, 0, tzinfo=ZONE)) == ()


def test_schedule_started_after_due_does_not_catch_up_startup_work() -> None:
    now = datetime(2026, 7, 15, 9, 0, tzinfo=ZONE)
    schedule = MaintenanceSchedule(MaintenanceScheduleSettings(), now=now)

    assert schedule.due(now) == ()
    assert schedule.due(now + timedelta(minutes=1)) == ()


def test_schedule_collapses_multi_day_sleep_to_one_request() -> None:
    start = datetime(2026, 7, 15, 0, 0, tzinfo=ZONE)
    schedule = MaintenanceSchedule(MaintenanceScheduleSettings(), now=start)

    requests = schedule.due(start + timedelta(days=3, minutes=20))

    assert len(requests) == 1
    assert requests[0].scope is MaintenanceScope.DAILY
