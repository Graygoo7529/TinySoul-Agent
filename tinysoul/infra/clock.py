"""Explicit timezone clock shared by Agent and environment adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tinysoul.infra.time import CalendarDay

from .time import CalendarDayError


class CalendarClock(Protocol):
    """Provide aware wall time and its configured calendar day."""

    def now(self) -> datetime:
        ...

    def today(self) -> CalendarDay:
        ...


@dataclass(frozen=True)
class IanaCalendarClock:
    """Calendar clock backed by one explicit IANA timezone."""

    timezone: str = "Asia/Shanghai"

    def __post_init__(self) -> None:
        if not isinstance(self.timezone, str) or not self.timezone:
            raise CalendarDayError("Clock timezone must be non-empty")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise CalendarDayError(
                f"Unknown IANA calendar timezone: {self.timezone}"
            ) from exc

    def now(self) -> datetime:
        return datetime.now(ZoneInfo(self.timezone))

    def today(self) -> CalendarDay:
        return CalendarDay(self.now().date())
