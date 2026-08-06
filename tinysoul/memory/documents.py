"""Strict Markdown/frontmatter documents owned by Memory."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from hashlib import sha256
import re
from typing import TypeVar, TypedDict, cast

import yaml
from yaml.resolver import BaseResolver

from .errors import MemoryContractError, MemoryInvariantError
from .links import MemoryKind, MemoryLink


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
class MemoryActivity:
    last_activated_on: date
    activation_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.last_activated_on, date):
            raise MemoryContractError("Memory activity date must be a date")
        if (
            isinstance(self.activation_count, bool)
            or not isinstance(self.activation_count, int)
            or self.activation_count < 0
        ):
            raise MemoryContractError("Memory activation_count cannot be negative")


@dataclass(frozen=True)
class DailyMemoryDocument:
    day: date
    revision: int
    created_on: date
    updated_on: date
    session_revision: int
    active_memory_digest: str
    content: str

    def __post_init__(self) -> None:
        if not all(
            isinstance(item, date)
            for item in (self.day, self.created_on, self.updated_on)
        ):
            raise MemoryContractError("Daily Memory dates must be dates")
        _non_negative_int(self.revision, "Daily Memory revision")
        _non_negative_int(self.session_revision, "Daily Memory session_revision")
        _digest(self.active_memory_digest, "Daily Memory active_memory_digest")
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
    activity: MemoryActivity
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
        if not isinstance(self.created_on, date) or not isinstance(self.updated_on, date):
            raise MemoryContractError("Memory created_on/updated_on must be dates")
        if self.created_on > self.updated_on:
            raise MemoryContractError("Memory created_on exceeds updated_on")
        if not isinstance(self.activity, MemoryActivity):
            raise MemoryContractError("Memory activity is invalid")
        _content(self.content, "Persistent Memory")
        relations = _links(self.relations, "relations")
        evidence = _links(self.evidence, "evidence")
        if any(link.kind not in {MemoryKind.ENTITY, MemoryKind.CONCEPT} for link in relations):
            raise MemoryContractError("Memory relations may only target entity/concept")
        if any(link.kind not in {MemoryKind.DAILY, MemoryKind.FACT, MemoryKind.NOTE} for link in evidence):
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
            raise MemoryContractError("Active Note Memory requires entity/concept relations")

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


class _KnowledgeFields(TypedDict):
    cite: str
    status: MemoryStatus
    created_on: date
    updated_on: date
    activity: MemoryActivity
    content: str
    relations: tuple[MemoryLink, ...]
    evidence: tuple[MemoryLink, ...]
    redirect_to: MemoryLink | None
    confidence: MemoryConfidence | None


_INLINE_LINK = re.compile(
    r"(?<![A-Za-z0-9])memory:(?:daily|entity|concept|fact|note)/[^\s<>\]\[(){}]+"
)


def inline_memory_links(text: str) -> tuple[MemoryLink, ...]:
    links: list[MemoryLink] = []
    for raw in _INLINE_LINK.findall(text):
        value = raw.rstrip(".,;:!?，。；：！？'\"")
        try:
            link = MemoryLink.parse(value)
        except MemoryContractError:
            continue
        if link not in links:
            links.append(link)
    return tuple(links)


class MemoryDocumentCodec:
    """Parse and deterministically render all persistent Memory Markdown."""

    def parse(self, link: MemoryLink, text: str) -> PersistentMemoryDocument:
        if not isinstance(link, MemoryLink):
            raise MemoryContractError("Memory codec requires a MemoryLink")
        frontmatter, content = _split_frontmatter(text)
        version = _required_int(frontmatter, "schema_version")
        if version != 1:
            raise MemoryInvariantError("Unsupported Memory schema_version")
        raw_kind = _required_text(frontmatter, "kind")
        if raw_kind != link.kind.value:
            raise MemoryInvariantError("Memory kind does not match its Link")
        if link.kind is MemoryKind.DAILY:
            return self._parse_daily(link, frontmatter, content)
        return self._parse_knowledge(link, frontmatter, content)

    def render(self, document: PersistentMemoryDocument) -> str:
        if isinstance(document, DailyMemoryDocument):
            metadata: dict[str, object] = {
                "schema_version": 1,
                "kind": "daily",
                "day": document.day.isoformat(),
                "revision": document.revision,
                "created_on": document.created_on.isoformat(),
                "updated_on": document.updated_on.isoformat(),
                "session_revision": document.session_revision,
                "active_memory_digest": document.active_memory_digest,
            }
            content = f"# {document.day.isoformat()}\n\n{document.content.strip()}"
            return _render_file(metadata, content)
        metadata = {
            "schema_version": 1,
            "kind": document.kind.value,
            "cite": document.cite,
            "status": document.status.value,
            "created_on": document.created_on.isoformat(),
            "updated_on": document.updated_on.isoformat(),
            "activity": {
                "last_activated_on": document.activity.last_activated_on.isoformat(),
                "activation_count": document.activity.activation_count,
            },
            "relations": [str(link) for link in document.relations],
            "evidence": [str(link) for link in document.evidence],
            "redirect_to": (
                str(document.redirect_to) if document.redirect_to is not None else None
            ),
        }
        if document.confidence is not None:
            metadata["confidence"] = document.confidence.value
        if isinstance(document, FactMemoryDocument):
            metadata["summary"] = document.summary
        if isinstance(document, NoteMemoryDocument):
            metadata["title"] = document.title
        return _render_file(metadata, document.content.strip())

    def stored(
        self,
        document: PersistentMemoryDocument,
    ) -> StoredMemoryDocument:
        text = self.render(document)
        return StoredMemoryDocument(
            document=document,
            text=text,
            digest=sha256(text.encode("utf-8")).hexdigest(),
        )

    def _parse_daily(
        self,
        link: MemoryLink,
        values: Mapping[str, object],
        content: str,
    ) -> DailyMemoryDocument:
        _exact_keys(
            values,
            {
                "schema_version",
                "kind",
                "day",
                "revision",
                "created_on",
                "updated_on",
                "session_revision",
                "active_memory_digest",
            },
        )
        day = _required_date(values, "day")
        heading = f"# {day.isoformat()}"
        stripped = content.strip()
        if not stripped.startswith(f"{heading}\n"):
            raise MemoryInvariantError("Daily Memory requires its canonical H1")
        body = stripped[len(heading) :].strip()
        if day != link.day:
            raise MemoryInvariantError("Daily Memory day does not match its Link")
        return DailyMemoryDocument(
            day=day,
            revision=_required_int(values, "revision"),
            created_on=_required_date(values, "created_on"),
            updated_on=_required_date(values, "updated_on"),
            session_revision=_required_int(values, "session_revision"),
            active_memory_digest=_required_text(values, "active_memory_digest"),
            content=body,
        )

    def _parse_knowledge(
        self,
        link: MemoryLink,
        values: Mapping[str, object],
        content: str,
    ) -> PersistentMemoryDocument:
        common = {
            "schema_version",
            "kind",
            "cite",
            "status",
            "created_on",
            "updated_on",
            "activity",
            "relations",
            "evidence",
            "redirect_to",
        }
        allowed = set(common)
        if link.kind is MemoryKind.FACT:
            allowed.update({"summary", "confidence"})
        elif link.kind is MemoryKind.NOTE:
            allowed.update({"title", "confidence"})
        else:
            allowed.add("confidence")
        _exact_keys(values, allowed, required=common)
        cite = _required_text(values, "cite")
        if cite != link.cite:
            raise MemoryInvariantError("Memory cite does not match its Link")
        raw_activity = values.get("activity")
        if not isinstance(raw_activity, Mapping):
            raise MemoryInvariantError("Memory activity must be a mapping")
        activity_values = cast(Mapping[str, object], raw_activity)
        _exact_keys(
            activity_values,
            {"last_activated_on", "activation_count"},
        )
        status = _enum(MemoryStatus, values, "status")
        created_on = _required_date(values, "created_on")
        updated_on = _required_date(values, "updated_on")
        activity = MemoryActivity(
            last_activated_on=_required_date(activity_values, "last_activated_on"),
            activation_count=_required_int(activity_values, "activation_count"),
        )
        relations = _link_list(values.get("relations"), "relations")
        evidence = _link_list(values.get("evidence"), "evidence")
        redirect_to = _optional_link(values.get("redirect_to"))
        confidence = _optional_enum(MemoryConfidence, values.get("confidence"))
        common_values: _KnowledgeFields = {
            "cite": cite,
            "status": status,
            "created_on": created_on,
            "updated_on": updated_on,
            "activity": activity,
            "content": content.strip(),
            "relations": relations,
            "evidence": evidence,
            "redirect_to": redirect_to,
            "confidence": confidence,
        }
        if link.kind is MemoryKind.ENTITY:
            return EntityMemoryDocument(**common_values)
        if link.kind is MemoryKind.CONCEPT:
            return ConceptMemoryDocument(**common_values)
        if link.kind is MemoryKind.FACT:
            return FactMemoryDocument(
                **common_values,
                summary=_required_text(values, "summary"),
            )
        if link.kind is MemoryKind.NOTE:
            return NoteMemoryDocument(
                **common_values,
                title=_required_text(values, "title"),
            )
        raise MemoryInvariantError("Unsupported persistent Memory kind")


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(
    loader: _UniqueKeyLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise MemoryInvariantError(f"Duplicate Memory frontmatter key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(
    BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def _split_frontmatter(text: str) -> tuple[Mapping[str, object], str]:
    if not isinstance(text, str) or not text.startswith("---\n"):
        raise MemoryInvariantError("Memory document requires YAML frontmatter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise MemoryInvariantError("Memory frontmatter is not terminated")
    raw = text[4:end]
    try:
        values = yaml.load(raw, Loader=_UniqueKeyLoader)
    except MemoryInvariantError:
        raise
    except yaml.YAMLError as exc:
        raise MemoryInvariantError("Memory frontmatter is invalid YAML") from exc
    if not isinstance(values, Mapping) or any(not isinstance(key, str) for key in values):
        raise MemoryInvariantError("Memory frontmatter must be a string-key mapping")
    return cast(Mapping[str, object], values), text[end + 5 :]


def _render_file(metadata: Mapping[str, object], content: str) -> str:
    _content(content, "Persistent Memory")
    frontmatter = yaml.safe_dump(
        dict(metadata),
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).rstrip()
    return f"---\n{frontmatter}\n---\n\n{content.strip()}\n"


def _exact_keys(
    values: Mapping[str, object],
    allowed: set[str],
    *,
    required: set[str] | None = None,
) -> None:
    unknown = set(values) - allowed
    missing = (required if required is not None else allowed) - set(values)
    if unknown:
        raise MemoryInvariantError(
            f"Unknown Memory frontmatter fields: {', '.join(sorted(unknown))}"
        )
    if missing:
        raise MemoryInvariantError(
            f"Missing Memory frontmatter fields: {', '.join(sorted(missing))}"
        )


def _required_text(values: Mapping[str, object], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MemoryInvariantError(f"Memory {key} must be non-empty text")
    return value


def _required_int(values: Mapping[str, object], key: str) -> int:
    value = values.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MemoryInvariantError(f"Memory {key} must be a non-negative integer")
    return value


def _required_date(values: Mapping[str, object], key: str) -> date:
    value = _required_text(values, key)
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise MemoryInvariantError(f"Memory {key} must be an ISO date") from exc
    if parsed.isoformat() != value:
        raise MemoryInvariantError(f"Memory {key} is not canonical")
    return parsed


def _link_list(value: object, key: str) -> tuple[MemoryLink, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise MemoryInvariantError(f"Memory {key} must be a list")
    if any(not isinstance(item, str) for item in value):
        raise MemoryInvariantError(f"Memory {key} contains a non-text Link")
    try:
        return _links(
            tuple(MemoryLink.parse(item) for item in cast(Sequence[str], value)),
            key,
        )
    except (MemoryContractError, TypeError) as exc:
        raise MemoryInvariantError(f"Memory {key} contains an invalid Link") from exc


def _optional_link(value: object) -> MemoryLink | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise MemoryInvariantError("Memory redirect_to must be a Link or null")
    try:
        return MemoryLink.parse(value)
    except MemoryContractError as exc:
        raise MemoryInvariantError("Memory redirect_to is invalid") from exc


_EnumValue = TypeVar("_EnumValue", bound=StrEnum)


def _enum(
    enum_type: type[_EnumValue],
    values: Mapping[str, object],
    key: str,
) -> _EnumValue:
    value = _required_text(values, key)
    try:
        return enum_type(value)
    except ValueError as exc:
        raise MemoryInvariantError(f"Memory {key} is invalid") from exc


def _optional_enum(
    enum_type: type[_EnumValue],
    value: object,
) -> _EnumValue | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise MemoryInvariantError("Memory enum value must be text")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise MemoryInvariantError("Memory enum value is invalid") from exc


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
    if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
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
            raise MemoryContractError(f"{owner} cannot contain a setext level-1 heading")


def _non_negative_int(value: object, owner: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MemoryContractError(f"{owner} cannot be negative")


def _digest(value: object, owner: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise MemoryContractError(f"{owner} must be a sha256 digest")


def _normalize_statement(value: str) -> str:
    return " ".join(value.strip().split())
