from __future__ import annotations

from pathlib import Path

import pytest

from tinysoul.infra.time import CalendarDay
from tinysoul.plugins.reflection import (ReflectionAvailability, ReflectionAvailabilityStore, ReflectionInvariantError)


DAY = CalendarDay.parse("2026-08-04")
PENDING = CalendarDay.parse("2026-08-03")


def test_availability_store_round_trip(tmp_path: Path) -> None:
    store = ReflectionAvailabilityStore(tmp_path)
    expected = ReflectionAvailability(
        checked_day=DAY,
        home_change_count=2,
        home_skill_memory_count=1,
        memory_days=(PENDING,),
    )

    store.save(expected)

    assert store.require() == expected
    assert store.path == tmp_path.resolve() / "availability.json"


def test_availability_store_rejects_unknown_fields(tmp_path: Path) -> None:
    path = tmp_path / "availability.json"
    path.write_text(
        '{"schema_version":1,"checked_day":"2026-08-04",'
        '"home":{"change_count":0,"skill_memory_count":0},'
        '"memory_days":[],"plan":[]}',
        encoding="utf-8",
    )

    with pytest.raises(ReflectionInvariantError, match="fields"):
        ReflectionAvailabilityStore(tmp_path).require()
