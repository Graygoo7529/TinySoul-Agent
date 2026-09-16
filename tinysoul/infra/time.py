"""Owner-neutral time value objects shared across TinySoul modules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


class CalendarDayError(Exception):
    """Raised when a CalendarDay cannot be constructed or parsed."""


@dataclass(frozen=True, order=True)
class CalendarDay:
    """One calendar day whose timezone is chosen by the calling owner."""

    value: date

    def __post_init__(self) -> None:
        if not isinstance(self.value, date) or isinstance(self.value, datetime):
            raise CalendarDayError("CalendarDay.value must be a date")

    @classmethod
    def parse(cls, value: str) -> "CalendarDay":
        if not isinstance(value, str) or not value:
            raise CalendarDayError("Business day must be a non-empty ISO date")
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise CalendarDayError(f"Invalid business day: {value}") from exc
        if parsed.isoformat() != value:
            raise CalendarDayError(f"Business day must use ISO format: {value}")
        return cls(parsed)

    def __str__(self) -> str:
        return self.value.isoformat()
