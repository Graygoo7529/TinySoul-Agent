"""Business-day clock used by Program-level work."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tinysoul.infra.time import BusinessDay

from .errors import MaintenanceContractError


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
            raise MaintenanceContractError("Business clock timezone must be non-empty")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise MaintenanceContractError(
                f"Unknown IANA business timezone: {self.timezone}"
            ) from exc

    def now(self) -> datetime:
        return datetime.now(ZoneInfo(self.timezone))

    def today(self) -> BusinessDay:
        return BusinessDay(self.now().date())
