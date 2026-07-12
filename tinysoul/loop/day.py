"""Business-day clock used by Program-level work."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import LoopContractError


@dataclass(frozen=True, order=True)
class BusinessDay:
    """One calendar day in the configured TinySoul business timezone."""

    value: date

    def __post_init__(self) -> None:
        if not isinstance(self.value, date) or isinstance(self.value, datetime):
            raise LoopContractError("BusinessDay.value must be a date")

    @classmethod
    def parse(cls, value: str) -> "BusinessDay":
        if not isinstance(value, str) or not value:
            raise LoopContractError("Business day must be a non-empty ISO date")
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise LoopContractError(f"Invalid business day: {value}") from exc
        if parsed.isoformat() != value:
            raise LoopContractError(f"Business day must use ISO format: {value}")
        return cls(parsed)

    def __str__(self) -> str:
        return self.value.isoformat()


class BusinessClock(Protocol):
    """Provide aware wall time and its configured business day."""

    def now(self) -> datetime:
        ...

    def today(self) -> BusinessDay:
        ...


@dataclass(frozen=True)
class IanaBusinessClock:
    """Business clock backed by one explicit IANA timezone."""

    timezone: str = "Asia/Shanghai"

    def __post_init__(self) -> None:
        if not isinstance(self.timezone, str) or not self.timezone:
            raise LoopContractError("Business clock timezone must be non-empty")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise LoopContractError(
                f"Unknown IANA business timezone: {self.timezone}"
            ) from exc

    def now(self) -> datetime:
        return datetime.now(ZoneInfo(self.timezone))

    def today(self) -> BusinessDay:
        return BusinessDay(self.now().date())
