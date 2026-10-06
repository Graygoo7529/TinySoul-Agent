"""Strict Markdown/frontmatter documents owned by Memory."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from enum import StrEnum
from hashlib import sha256
import re

from tinysoul.infra.references import (
    markdown_references,
    relative_reference,
    ReferenceError,
)
from typing import TypeVar, TypedDict, cast

import yaml
from yaml.resolver import BaseResolver

from ..errors import MemoryContractError, MemoryInvariantError
from ..refs import MemoryKind, MemoryRef


from .models import (
    MemoryStatus,
    MemoryConfidence,
    DailyMemoryDocument,
    EntityMemoryDocument,
    ConceptMemoryDocument,
    FactMemoryDocument,
    NoteMemoryDocument,
    PersistentMemoryDocument,
    StoredMemoryDocument,
)
from .models import _content, _refs


class _KnowledgeFields(TypedDict):
    cite: str
    status: MemoryStatus
    created_on: date
    updated_on: date
    content: str
    relations: tuple[MemoryRef, ...]
    evidence: tuple[MemoryRef, ...]
    redirect_to: MemoryRef | None
    confidence: MemoryConfidence | None


def inline_memory_refs(
    text: str, *, source: MemoryRef | None = None
) -> tuple[MemoryRef, ...]:
    refs: list[MemoryRef] = []
    for reference in markdown_references(text):
        try:
            target = (
                relative_reference(
                    reference.target, source_path=source.relative_path, prefix="memory:"
                )
                if source
                else reference.target
            )
            value = target.partition("#")[0]
            if not value.startswith("memory:"):
                continue
            ref = (
                MemoryRef.from_relative(value.removeprefix("memory:"))
                if value.endswith(".md")
                else MemoryRef.parse(value)
            )
        except (MemoryContractError, ReferenceError):
            continue
        if ref not in refs:
            refs.append(ref)
    return tuple(refs)


class MemoryDocumentCodec:
    """Parse and deterministically render all persistent Memory Markdown."""

    def parse(self, ref: MemoryRef, text: str) -> PersistentMemoryDocument:
        if not isinstance(ref, MemoryRef):
            raise MemoryContractError("Memory codec requires a MemoryRef")
        frontmatter, content = _split_frontmatter(text)
        version = _required_int(frontmatter, "schema_version")
        if version != 2:
            raise MemoryInvariantError("Unsupported Memory schema_version")
        raw_kind = _required_text(frontmatter, "kind")
        if raw_kind != ref.kind.value:
            raise MemoryInvariantError("Memory kind does not match its reference")
        if ref.kind is MemoryKind.DAILY:
            return self._parse_daily(ref, frontmatter, content)
        return self._parse_knowledge(ref, frontmatter, content)

    def render(self, document: PersistentMemoryDocument) -> str:
        if isinstance(document, DailyMemoryDocument):
            metadata: dict[str, object] = {
                "schema_version": 2,
                "kind": "daily",
                "day": document.day.isoformat(),
                "created_on": document.created_on.isoformat(),
                "updated_on": document.updated_on.isoformat(),
            }
            content = f"# {document.day.isoformat()}\n\n{document.content.strip()}"
            return _render_file(metadata, content)
        metadata = {
            "schema_version": 2,
            "kind": document.kind.value,
            "cite": document.cite,
            "status": document.status.value,
            "created_on": document.created_on.isoformat(),
            "updated_on": document.updated_on.isoformat(),
            "relations": [str(ref) for ref in document.relations],
            "evidence": [str(ref) for ref in document.evidence],
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
        ref: MemoryRef,
        values: Mapping[str, object],
        content: str,
    ) -> DailyMemoryDocument:
        _exact_keys(
            values,
            {
                "schema_version",
                "kind",
                "day",
                "created_on",
                "updated_on",
            },
        )
        day = _required_date(values, "day")
        heading = f"# {day.isoformat()}"
        stripped = content.strip()
        if not stripped.startswith(f"{heading}\n"):
            raise MemoryInvariantError("Daily Memory requires its canonical H1")
        body = stripped[len(heading) :].strip()
        if day != ref.day:
            raise MemoryInvariantError("Daily Memory day does not match its reference")
        return DailyMemoryDocument(
            day=day,
            created_on=_required_date(values, "created_on"),
            updated_on=_required_date(values, "updated_on"),
            content=body,
        )

    def _parse_knowledge(
        self,
        ref: MemoryRef,
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
            "relations",
            "evidence",
            "redirect_to",
        }
        allowed = set(common)
        if ref.kind is MemoryKind.FACT:
            allowed.update({"summary", "confidence"})
        elif ref.kind is MemoryKind.NOTE:
            allowed.update({"title", "confidence"})
        else:
            allowed.add("confidence")
        _exact_keys(values, allowed, required=common)
        cite = _required_text(values, "cite")
        if cite != ref.cite:
            raise MemoryInvariantError("Memory cite does not match its reference")
        status = _enum(MemoryStatus, values, "status")
        created_on = _required_date(values, "created_on")
        updated_on = _required_date(values, "updated_on")
        relations = _ref_list(values.get("relations"), "relations")
        evidence = _ref_list(values.get("evidence"), "evidence")
        redirect_to = _optional_ref(values.get("redirect_to"))
        confidence = _optional_enum(MemoryConfidence, values.get("confidence"))
        common_values: _KnowledgeFields = {
            "cite": cite,
            "status": status,
            "created_on": created_on,
            "updated_on": updated_on,
            "content": content.strip(),
            "relations": relations,
            "evidence": evidence,
            "redirect_to": redirect_to,
            "confidence": confidence,
        }
        if ref.kind is MemoryKind.ENTITY:
            return EntityMemoryDocument(**common_values)
        if ref.kind is MemoryKind.CONCEPT:
            return ConceptMemoryDocument(**common_values)
        if ref.kind is MemoryKind.FACT:
            return FactMemoryDocument(
                **common_values,
                summary=_required_text(values, "summary"),
            )
        if ref.kind is MemoryKind.NOTE:
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
    if not isinstance(values, Mapping) or any(
        not isinstance(key, str) for key in values
    ):
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


def _ref_list(value: object, key: str) -> tuple[MemoryRef, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise MemoryInvariantError(f"Memory {key} must be a list")
    if any(not isinstance(item, str) for item in value):
        raise MemoryInvariantError(f"Memory {key} contains a non-text reference")
    try:
        return _refs(
            tuple(MemoryRef.parse(item) for item in cast(Sequence[str], value)),
            key,
        )
    except (MemoryContractError, TypeError) as exc:
        raise MemoryInvariantError(
            f"Memory {key} contains an invalid reference"
        ) from exc


def _optional_ref(value: object) -> MemoryRef | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise MemoryInvariantError("Memory redirect_to must be a reference or null")
    try:
        return MemoryRef.parse(value)
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
