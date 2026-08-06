"""Canonical Memory links and Context-only Memory references."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import PurePosixPath
import re

from .errors import MemoryContractError


class MemoryKind(StrEnum):
    DAILY = "daily"
    ENTITY = "entity"
    CONCEPT = "concept"
    FACT = "fact"
    NOTE = "note"


class MemoryBackgroundRef(StrEnum):
    CURRENT = "memory:current"
    LATEST = "memory:latest"
    TARGET = "memory:target"


_LINK = re.compile(r"memory:(daily|entity|concept|fact|note)/([^/]+)\Z")
_NAME_CITE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_FACT_CITE = re.compile(r"f-[0-9a-f]{12,64}\Z")
_NOTE_CITE = re.compile(r"n-[0-9a-f]{12,64}\Z")
_DAILY_PATH = re.compile(
    r"daily/(\d{4})/(\d{2})/(\d{4}-\d{2}-\d{2})\.md\Z"
)
_OTHER_PATH = re.compile(r"(entity|concept|fact|note)/([^/]+)\.md\Z")
_WINDOWS_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


@dataclass(frozen=True, order=True)
class MemoryLink:
    """One canonical persistent Memory identity."""

    kind: MemoryKind
    cite: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, MemoryKind):
            raise MemoryContractError("Memory link kind must be a MemoryKind")
        _validate_cite(self.kind, self.cite)

    @classmethod
    def parse(cls, value: str) -> "MemoryLink":
        if not isinstance(value, str):
            raise MemoryContractError("Memory link must be text")
        match = _LINK.fullmatch(value)
        if match is None:
            raise MemoryContractError(
                "Memory link must use memory:<daily|entity|concept|fact|note>/<cite>"
            )
        link = cls(MemoryKind(match.group(1)), match.group(2))
        if str(link) != value:
            raise MemoryContractError("Memory link is not canonical")
        return link

    @classmethod
    def daily(cls, day: date) -> "MemoryLink":
        if not isinstance(day, date):
            raise MemoryContractError("Daily Memory day must be a date")
        return cls(MemoryKind.DAILY, day.isoformat())

    @classmethod
    def from_relative(cls, relative: str) -> "MemoryLink":
        if (
            not isinstance(relative, str)
            or PurePosixPath(relative).is_absolute()
            or "\\" in relative
        ):
            raise MemoryContractError("Memory relative path must be canonical")
        daily = _DAILY_PATH.fullmatch(relative)
        if daily is not None:
            link = cls.parse(f"memory:daily/{daily.group(3)}")
            day = link.day
            if daily.group(1) != f"{day.year:04d}" or daily.group(2) != f"{day.month:02d}":
                raise MemoryContractError(
                    "Daily Memory path date does not match its directories"
                )
            return link
        other = _OTHER_PATH.fullmatch(relative)
        if other is None:
            raise MemoryContractError("Memory path does not map to a persistent link")
        return cls.parse(f"memory:{other.group(1)}/{other.group(2)}")

    @property
    def day(self) -> date:
        if self.kind is not MemoryKind.DAILY:
            raise MemoryContractError("Only daily Memory links have a day")
        try:
            return date.fromisoformat(self.cite)
        except ValueError as exc:  # pragma: no cover - guarded by construction
            raise MemoryContractError("Daily Memory cite is invalid") from exc

    @property
    def relative_path(self) -> str:
        if self.kind is MemoryKind.DAILY:
            day = self.day
            return f"daily/{day.year:04d}/{day.month:02d}/{day.isoformat()}.md"
        return f"{self.kind.value}/{self.cite}.md"

    def __str__(self) -> str:
        return f"memory:{self.kind.value}/{self.cite}"


def parse_persistent_memory_link(value: str) -> MemoryLink:
    if value in {item.value for item in MemoryBackgroundRef}:
        raise MemoryContractError("Context Memory references are not persistent links")
    return MemoryLink.parse(value)


def _validate_cite(kind: MemoryKind, cite: object) -> None:
    if not isinstance(cite, str) or not cite:
        raise MemoryContractError("Memory cite must be non-empty text")
    if kind is MemoryKind.DAILY:
        try:
            parsed = date.fromisoformat(cite)
        except ValueError as exc:
            raise MemoryContractError("Daily Memory cite must be an ISO date") from exc
        if parsed.isoformat() != cite:
            raise MemoryContractError("Daily Memory cite is not canonical")
        return
    if kind in {MemoryKind.ENTITY, MemoryKind.CONCEPT} and len(cite) > 120:
        raise MemoryContractError(f"{kind.value} Memory cite exceeds 120 characters")
    pattern = {
        MemoryKind.ENTITY: _NAME_CITE,
        MemoryKind.CONCEPT: _NAME_CITE,
        MemoryKind.FACT: _FACT_CITE,
        MemoryKind.NOTE: _NOTE_CITE,
    }[kind]
    if pattern.fullmatch(cite) is None:
        raise MemoryContractError(f"Invalid {kind.value} Memory cite")
    if cite.lower() in _WINDOWS_RESERVED:
        raise MemoryContractError("Memory cite is a Windows reserved name")
