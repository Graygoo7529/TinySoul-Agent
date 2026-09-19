"""Archive owner: deterministic rollover journal and frozen-day catalog."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tinysoul.infra.time import CalendarDay

from .errors import ArchiveContractError


@dataclass(frozen=True)
class ArchiveProjection:
    """Owner-neutral roots for one finalized Business Day archive."""

    day: CalendarDay
    root: Path
    session_root: Path
    workspace_root: Path

    def __post_init__(self) -> None:
        if not isinstance(self.day, CalendarDay):
            raise ArchiveContractError("Archive projection day is invalid")
        for name in ("root", "session_root", "workspace_root"):
            value = getattr(self, name)
            if not isinstance(value, Path) or not value.is_absolute():
                raise ArchiveContractError(
                    f"Archive projection {name} must be an absolute path"
                )
