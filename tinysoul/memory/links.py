"""Stable Memory-owned date links."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from pathlib import PurePosixPath

from .errors import MemoryContractError


_MEMORY_LINK = re.compile(r"memory:(\d{4}-\d{2}-\d{2})\.md\Z")
_MEMORY_RELATIVE = re.compile(
    r"(\d{4})/(\d{2})/(\d{4}-\d{2}-\d{2})\.md\Z"
)


@dataclass(frozen=True, order=True)
class MemoryLink:
    """One canonical `memory:YYYY-MM-DD.md` link."""

    day: date

    def __post_init__(self) -> None:
        if not isinstance(self.day, date):
            raise MemoryContractError("Memory link day must be a date")

    @classmethod
    def parse(cls, value: str) -> "MemoryLink":
        if not isinstance(value, str):
            raise MemoryContractError("Memory link must be text")
        match = _MEMORY_LINK.fullmatch(value)
        if match is None:
            raise MemoryContractError(
                "Memory link must use memory:YYYY-MM-DD.md"
            )
        try:
            parsed = date.fromisoformat(match.group(1))
        except ValueError as exc:
            raise MemoryContractError("Memory link contains an invalid date") from exc
        link = cls(parsed)
        if str(link) != value:
            raise MemoryContractError("Memory link is not canonical")
        return link

    @classmethod
    def from_relative(cls, relative: str) -> "MemoryLink":
        if not isinstance(relative, str):
            raise MemoryContractError("Memory relative path must be text")
        if PurePosixPath(relative).is_absolute() or "\\" in relative:
            raise MemoryContractError("Memory relative path must be canonical")
        match = _MEMORY_RELATIVE.fullmatch(relative)
        if match is None:
            raise MemoryContractError("Memory path must use yyyy/mm/yyyy-mm-dd.md")
        link = cls.parse(f"memory:{match.group(3)}.md")
        if match.group(1) != f"{link.day.year:04d}" or match.group(2) != f"{link.day.month:02d}":
            raise MemoryContractError("Memory path date does not match its directories")
        return link

    @property
    def relative_path(self) -> str:
        return (
            f"{self.day.year:04d}/{self.day.month:02d}/"
            f"{self.day.isoformat()}.md"
        )

    def __str__(self) -> str:
        return f"memory:{self.day.isoformat()}.md"
