"""Strict Markdown/frontmatter documents owned by Memory."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
import re


from ..errors import MemoryContractError
from ..links import MemoryKind, MemoryLink


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    MERGED = "merged"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"


class MemoryConfidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class DailyMemoryDocument:
    day: date
    created_on: date
    updated_on: date
    content: str

    def __post_init__(self) -> None:
        if not all(
            isinstance(item, date)
            for item in (self.day, self.created_on, self.updated_on)
        ):
            raise MemoryContractError("Daily Memory dates must be dates")
        _content(self.content, "Daily Memory")
        _without_h1(self.content, "Daily Memory content")
        if self.created_on != self.day or self.updated_on != self.day:
            raise MemoryContractError(
                "Daily Memory created_on/updated_on must equal its target day"
            )

    @property
    def link(self) -> MemoryLink:
        return MemoryLink.daily(self.day)

    @property
    def kind(self) -> MemoryKind:
        return MemoryKind.DAILY

    @property
    def status(self) -> MemoryStatus:
        return MemoryStatus.ACTIVE

    @property
    def display(self) -> str:
        return self.day.isoformat()


@dataclass(frozen=True)
class _KnowledgeDocument:
    cite: str
    status: MemoryStatus
    created_on: date
    updated_on: date
    content: str
    relations: tuple[MemoryLink, ...] = field(default_factory=tuple)
    evidence: tuple[MemoryLink, ...] = field(default_factory=tuple)
    redirect_to: MemoryLink | None = None
    confidence: MemoryConfidence | None = None

    @property
    def kind(self) -> MemoryKind:
        raise NotImplementedError

    def __post_init__(self) -> None:
        if not isinstance(self.status, MemoryStatus):
            raise MemoryContractError("Memory status is invalid")
        if not isinstance(self.created_on, date) or not isinstance(
            self.updated_on, date
        ):
            raise MemoryContractError("Memory created_on/updated_on must be dates")
        if self.created_on > self.updated_on:
            raise MemoryContractError("Memory created_on exceeds updated_on")
        _content(self.content, "Persistent Memory")
        relations = _links(self.relations, "relations")
        evidence = _links(self.evidence, "evidence")
        if any(
            link.kind not in {MemoryKind.ENTITY, MemoryKind.CONCEPT}
            for link in relations
        ):
            raise MemoryContractError("Memory relations may only target entity/concept")
        if any(
            link.kind not in {MemoryKind.DAILY, MemoryKind.FACT, MemoryKind.NOTE}
            for link in evidence
        ):
            raise MemoryContractError("Memory evidence may only target daily/fact/note")
        if self.status is MemoryStatus.ACTIVE and self.redirect_to is not None:
            raise MemoryContractError("Active Memory cannot redirect")
        if self.status is not MemoryStatus.ACTIVE and self.redirect_to is None:
            raise MemoryContractError("Non-active Memory requires redirect_to")
        if self.redirect_to is not None and self.redirect_to.kind is MemoryKind.DAILY:
            raise MemoryContractError("Memory redirect_to cannot target daily")
        if (
            self.status in {MemoryStatus.MERGED, MemoryStatus.SUPERSEDED}
            and self.redirect_to is not None
            and self.redirect_to.kind is not self.kind
        ):
            raise MemoryContractError(
                "Merged/superseded Memory must redirect to the same kind"
            )
        if self.confidence is not None and not isinstance(
            self.confidence, MemoryConfidence
        ):
            raise MemoryContractError("Memory confidence is invalid")
        object.__setattr__(self, "relations", relations)
        object.__setattr__(self, "evidence", evidence)


@dataclass(frozen=True)
class EntityMemoryDocument(_KnowledgeDocument):
    @property
    def kind(self) -> MemoryKind:
        return MemoryKind.ENTITY

    @property
    def link(self) -> MemoryLink:
        return MemoryLink(self.kind, self.cite)

    @property
    def display(self) -> str:
        return self.cite


@dataclass(frozen=True)
class ConceptMemoryDocument(_KnowledgeDocument):
    @property
    def kind(self) -> MemoryKind:
        return MemoryKind.CONCEPT

    @property
    def link(self) -> MemoryLink:
        return MemoryLink(self.kind, self.cite)

    @property
    def display(self) -> str:
        return self.cite


@dataclass(frozen=True)
class FactMemoryDocument(_KnowledgeDocument):
    summary: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        _one_line(self.summary, "Fact summary", max_chars=480)
        if self.confidence is None:
            raise MemoryContractError("Fact Memory requires confidence")
        if not any(link.kind is MemoryKind.DAILY for link in self.evidence):
            raise MemoryContractError("Fact Memory requires daily evidence")
        if self.status is MemoryStatus.ACTIVE:
            _one_line(self.content, "Active Fact content")
            if _normalize_statement(self.content) != _normalize_statement(self.summary):
                raise MemoryContractError("Active Fact content must equal its summary")

    @property
    def kind(self) -> MemoryKind:
        return MemoryKind.FACT

    @property
    def link(self) -> MemoryLink:
        return MemoryLink(self.kind, self.cite)

    @property
    def display(self) -> str:
        return self.summary


@dataclass(frozen=True)
class NoteMemoryDocument(_KnowledgeDocument):
    title: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        _one_line(self.title, "Note title", max_chars=240)
        if self.status is MemoryStatus.ACTIVE and not self.relations:
            raise MemoryContractError(
                "Active Note Memory requires entity/concept relations"
            )

    @property
    def kind(self) -> MemoryKind:
        return MemoryKind.NOTE

    @property
    def link(self) -> MemoryLink:
        return MemoryLink(self.kind, self.cite)

    @property
    def display(self) -> str:
        return self.title


PersistentMemoryDocument = (
    DailyMemoryDocument
    | EntityMemoryDocument
    | ConceptMemoryDocument
    | FactMemoryDocument
    | NoteMemoryDocument
)


@dataclass(frozen=True)
class StoredMemoryDocument:
    document: PersistentMemoryDocument
    text: str
    digest: str

    @property
    def link(self) -> MemoryLink:
        return self.document.link


def _links(values: Sequence[MemoryLink], key: str) -> tuple[MemoryLink, ...]:
    result = tuple(values)
    if any(not isinstance(item, MemoryLink) for item in result):
        raise MemoryContractError(f"Memory {key} must contain MemoryLink values")
    if len(set(result)) != len(result):
        raise MemoryContractError(f"Memory {key} cannot contain duplicate Links")
    return result


def _content(value: object, owner: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise MemoryContractError(f"{owner} content must be non-empty")


def _one_line(value: object, owner: str, *, max_chars: int | None = None) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or "\n" in value
        or "\r" in value
    ):
        raise MemoryContractError(f"{owner} must be one non-empty line")
    if max_chars is not None and len(value) > max_chars:
        raise MemoryContractError(f"{owner} exceeds {max_chars} characters")


def _without_h1(value: str, owner: str) -> None:
    lines = value.splitlines()
    for index, line in enumerate(lines):
        if re.match(r"^ {0,3}#(?:[ \t]|$)", line):
            raise MemoryContractError(f"{owner} cannot contain a level-1 heading")
        if (
            index > 0
            and lines[index - 1].strip()
            and re.fullmatch(r" {0,3}=+[ \t]*", line)
        ):
            raise MemoryContractError(
                f"{owner} cannot contain a setext level-1 heading"
            )


def _normalize_statement(value: str) -> str:
    return " ".join(value.strip().split())
