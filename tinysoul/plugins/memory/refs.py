"""Canonical Memory refs and Context-only Memory references."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import PurePosixPath

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


_REF = re.compile(r"memory:(daily|entity|concept|fact|note)/([^/]+)\Z")
_NAME_CITE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_FACT_CITE = re.compile(r"f-[0-9a-f]{12,64}\Z")
_NOTE_CITE = re.compile(r"n-[0-9a-f]{12,64}\Z")
_DAILY_PATH = re.compile(r"daily/(\d{4})/(\d{2})/(\d{4}-\d{2}-\d{2})\.md\Z")
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
class MemoryRef:
    """One canonical persistent Memory identity."""

    kind: MemoryKind
    cite: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, MemoryKind):
            raise MemoryContractError("Memory ref kind must be a MemoryKind")
        _validate_cite(self.kind, self.cite)

    @classmethod
    def parse(cls, value: str) -> "MemoryRef":
        if not isinstance(value, str):
            raise MemoryContractError("Memory ref must be text")
        match = _REF.fullmatch(value)
        if match is None:
            raise MemoryContractError(
                "Memory ref must use memory:<daily|entity|concept|fact|note>/<cite>"
            )
        ref = cls(MemoryKind(match.group(1)), match.group(2))
        if str(ref) != value:
            raise MemoryContractError("Memory ref is not canonical")
        return ref

    @classmethod
    def from_resource(cls, resource: str) -> "MemoryRef":
        """Normalize a persistent reference or Markdown resource path without reading."""
        body = resource.removeprefix("memory:")
        return cls.from_relative(body) if body.endswith(".md") else cls.parse(resource)

    @classmethod
    def daily(cls, day: date) -> "MemoryRef":
        if not isinstance(day, date):
            raise MemoryContractError("Daily Memory day must be a date")
        return cls(MemoryKind.DAILY, day.isoformat())

    @classmethod
    def from_relative(cls, relative: str) -> "MemoryRef":
        if (
            not isinstance(relative, str)
            or PurePosixPath(relative).is_absolute()
            or "\\" in relative
        ):
            raise MemoryContractError("Memory relative path must be canonical")
        daily = _DAILY_PATH.fullmatch(relative)
        if daily is not None:
            ref = cls.parse(f"memory:daily/{daily.group(3)}")
            day = ref.day
            if (
                daily.group(1) != f"{day.year:04d}"
                or daily.group(2) != f"{day.month:02d}"
            ):
                raise MemoryContractError(
                    "Daily Memory path date does not match its directories"
                )
            return ref
        other = _OTHER_PATH.fullmatch(relative)
        if other is None:
            raise MemoryContractError("Memory path does not map to a persistent ref")
        return cls.parse(f"memory:{other.group(1)}/{other.group(2)}")

    @property
    def day(self) -> date:
        if self.kind is not MemoryKind.DAILY:
            raise MemoryContractError("Only daily Memory refs have a day")
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


def parse_persistent_memory_ref(value: str) -> MemoryRef:
    if value in {item.value for item in MemoryBackgroundRef}:
        raise MemoryContractError("Context Memory references are not persistent refs")
    return MemoryRef.parse(value)


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
