"""Current Business Day explicit Memory.md ownership."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
import re
from typing import cast

import yaml
from yaml.resolver import BaseResolver

from tinysoul.infra.filesystem import atomic_write_text, read_text_prefix

from .errors import MemoryContractError, MemoryIOError, MemoryInvariantError


class MemoryPatchKind(StrEnum):
    APPEND = "append"
    REPLACE = "replace"
    REMOVE = "remove"
    CLEAR = "clear"


@dataclass(frozen=True)
class MemoryPatchOperation:
    kind: MemoryPatchKind
    text: str = ""
    old_text: str = ""
    new_text: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, MemoryPatchKind):
            raise MemoryContractError("Memory patch kind is invalid")
        if self.kind is MemoryPatchKind.APPEND:
            _non_empty(self.text, "append text")
            if self.old_text or self.new_text:
                raise MemoryContractError("Append only accepts text")
        elif self.kind is MemoryPatchKind.REPLACE:
            _non_empty(self.old_text, "replace old_text")
            if not isinstance(self.new_text, str):
                raise MemoryContractError("Replace new_text must be text")
            if self.text:
                raise MemoryContractError("Replace does not accept text")
        elif self.kind is MemoryPatchKind.REMOVE:
            _non_empty(self.text, "remove text")
            if self.old_text or self.new_text:
                raise MemoryContractError("Remove only accepts text")
        elif self.text or self.old_text or self.new_text:
            raise MemoryContractError("Clear does not accept text fields")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "MemoryPatchOperation":
        if not isinstance(value, Mapping):
            raise MemoryContractError("Memory patch operation must be an object")
        allowed = {"kind", "text", "old_text", "new_text"}
        if set(value) - allowed:
            raise MemoryContractError("Memory patch operation contains unknown fields")
        raw_kind = value.get("kind")
        if not isinstance(raw_kind, str):
            raise MemoryContractError("Memory patch operation requires kind")
        try:
            kind = MemoryPatchKind(raw_kind)
        except ValueError as exc:
            raise MemoryContractError("Memory patch kind is invalid") from exc
        return cls(
            kind=kind,
            text=_optional_text(value.get("text"), "text"),
            old_text=_optional_text(value.get("old_text"), "old_text"),
            new_text=_optional_text(value.get("new_text"), "new_text"),
        )


@dataclass(frozen=True)
class ActiveMemoryDocument:
    day: date
    revision: int
    updated_at: datetime | None
    content: str

    def __post_init__(self) -> None:
        if not isinstance(self.day, date):
            raise MemoryContractError("Active Memory day must be a date")
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 0
        ):
            raise MemoryContractError("Active Memory revision cannot be negative")
        if self.updated_at is not None and (
            not isinstance(self.updated_at, datetime)
            or self.updated_at.tzinfo is None
        ):
            raise MemoryContractError("Active Memory updated_at must include timezone")
        if not isinstance(self.content, str):
            raise MemoryContractError("Active Memory content must be text")


@dataclass(frozen=True)
class ActiveMemorySnapshot:
    document: ActiveMemoryDocument
    text: str
    digest: str

    @property
    def day(self) -> date:
        return self.document.day

    @property
    def content(self) -> str:
        return self.document.content


class ActiveMemoryStore:
    """Own the fixed Memory.md file under an injected Session root."""

    def __init__(self, *, session_root: Path, max_chars: int) -> None:
        if not isinstance(session_root, Path):
            raise MemoryContractError("Active Memory Session root must be a path")
        if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars <= 0:
            raise MemoryContractError("Active Memory limit must be positive")
        self._session_root = session_root
        self._max_chars = max_chars

    @property
    def session_root(self) -> Path:
        return self._session_root

    @property
    def path(self) -> Path:
        return self._session_root / "Memory.md"

    def initialize_day(self, day: date) -> ActiveMemorySnapshot:
        if not isinstance(day, date):
            raise MemoryContractError("Active Memory day must be a date")
        if not self._session_root.is_dir():
            raise MemoryInvariantError(
                "Session root must exist before Active Memory initialization"
            )
        if self.path.exists():
            return self.read(day)
        document = ActiveMemoryDocument(
            day=day,
            revision=0,
            updated_at=None,
            content="",
        )
        return self._write(document)

    def read(self, expected_day: date | None = None) -> ActiveMemorySnapshot:
        return self.read_from_root(self._session_root, expected_day=expected_day)

    def read_from_root(
        self,
        root: Path,
        *,
        expected_day: date | None = None,
    ) -> ActiveMemorySnapshot:
        path = root / "Memory.md"
        if path.is_symlink():
            raise MemoryInvariantError("Active Memory cannot be a symlink")
        if not path.is_file():
            raise MemoryInvariantError("Active Memory.md is missing")
        try:
            read = read_text_prefix(path, max_chars=self._max_chars + 1024)
        except UnicodeDecodeError as exc:
            raise MemoryInvariantError("Active Memory is not UTF-8") from exc
        except OSError as exc:
            raise MemoryIOError(f"Failed to read Active Memory: {exc}") from exc
        if read.truncated:
            raise MemoryInvariantError("Active Memory file exceeds its bounded size")
        document = _parse_active(read.text)
        if len(document.content) > self._max_chars:
            raise MemoryInvariantError("Active Memory content exceeds its limit")
        if expected_day is not None and document.day != expected_day:
            raise MemoryInvariantError("Active Memory day does not match Session day")
        return ActiveMemorySnapshot(
            document=document,
            text=read.text,
            digest=sha256(read.text.encode("utf-8")).hexdigest(),
        )

    def patch(
        self,
        *,
        day: date,
        expected_digest: str,
        operations: Sequence[MemoryPatchOperation],
    ) -> ActiveMemorySnapshot:
        if (
            not isinstance(expected_digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected_digest) is None
        ):
            raise MemoryContractError("Memory patch expected_digest is invalid")
        operations = tuple(operations)
        if not operations:
            raise MemoryContractError("Memory patch requires operations")
        if any(not isinstance(item, MemoryPatchOperation) for item in operations):
            raise MemoryContractError("Memory patch operations are invalid")
        current = self.read(day)
        if current.digest != expected_digest:
            raise MemoryContractError("Active Memory digest is stale")
        content = current.content
        for operation in operations:
            content = _apply_operation(content, operation)
        if len(content) > self._max_chars:
            raise MemoryContractError("Active Memory content exceeds its limit")
        if content == current.content:
            raise MemoryContractError("Memory patch did not change content")
        document = ActiveMemoryDocument(
            day=day,
            revision=current.document.revision + 1,
            updated_at=datetime.now(UTC),
            content=content,
        )
        # Re-check immediately before replace to catch external synchronization.
        if self.read(day).digest != expected_digest:
            raise MemoryContractError("Active Memory digest is stale")
        return self._write(document)

    def _write(self, document: ActiveMemoryDocument) -> ActiveMemorySnapshot:
        text = _render_active(document)
        try:
            atomic_write_text(self.path, text)
        except OSError as exc:
            raise MemoryIOError(f"Failed to write Active Memory: {exc}") from exc
        return ActiveMemorySnapshot(
            document=document,
            text=text,
            digest=sha256(text.encode("utf-8")).hexdigest(),
        )


def _apply_operation(content: str, operation: MemoryPatchOperation) -> str:
    if operation.kind is MemoryPatchKind.APPEND:
        if not content:
            return operation.text.strip()
        return f"{content.rstrip()}\n\n{operation.text.strip()}"
    if operation.kind is MemoryPatchKind.CLEAR:
        return ""
    needle = operation.old_text if operation.kind is MemoryPatchKind.REPLACE else operation.text
    count = content.count(needle)
    if count != 1:
        raise MemoryContractError(
            "Memory patch target must occur exactly once"
        )
    if operation.kind is MemoryPatchKind.REPLACE:
        return content.replace(needle, operation.new_text, 1)
    return content.replace(needle, "", 1).strip()


def _render_active(document: ActiveMemoryDocument) -> str:
    metadata = {
        "schema_version": 1,
        "kind": "active",
        "day": document.day.isoformat(),
        "revision": document.revision,
        "updated_at": (
            document.updated_at.isoformat() if document.updated_at is not None else None
        ),
    }
    frontmatter = yaml.safe_dump(metadata, sort_keys=False).rstrip()
    suffix = f"\n\n{document.content.strip()}\n" if document.content else "\n"
    return f"---\n{frontmatter}\n---{suffix}"


def _parse_active(text: str) -> ActiveMemoryDocument:
    if not text.startswith("---\n"):
        raise MemoryInvariantError("Active Memory requires YAML frontmatter")
    end = text.find("\n---", 4)
    if end < 0:
        raise MemoryInvariantError("Active Memory frontmatter is not terminated")
    try:
        values = yaml.load(text[4:end], Loader=_ActiveUniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise MemoryInvariantError("Active Memory frontmatter is invalid") from exc
    if not isinstance(values, Mapping):
        raise MemoryInvariantError("Active Memory frontmatter must be a mapping")
    values = cast(Mapping[str, object], values)
    expected = {"schema_version", "kind", "day", "revision", "updated_at"}
    if set(values) != expected:
        raise MemoryInvariantError("Active Memory frontmatter fields are invalid")
    if values.get("schema_version") != 1 or values.get("kind") != "active":
        raise MemoryInvariantError("Active Memory schema or kind is invalid")
    raw_day = values.get("day")
    if not isinstance(raw_day, str):
        raise MemoryInvariantError("Active Memory day must be text")
    try:
        day = date.fromisoformat(raw_day)
    except ValueError as exc:
        raise MemoryInvariantError("Active Memory day is invalid") from exc
    revision = values.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise MemoryInvariantError("Active Memory revision is invalid")
    raw_updated = values.get("updated_at")
    updated_at: datetime | None = None
    if raw_updated is not None:
        if not isinstance(raw_updated, str):
            raise MemoryInvariantError("Active Memory updated_at is invalid")
        try:
            updated_at = datetime.fromisoformat(raw_updated)
        except ValueError as exc:
            raise MemoryInvariantError("Active Memory updated_at is invalid") from exc
        if updated_at.tzinfo is None:
            raise MemoryInvariantError("Active Memory updated_at lacks timezone")
    content = text[end + 4 :].lstrip("\r\n").rstrip()
    return ActiveMemoryDocument(
        day=day,
        revision=revision,
        updated_at=updated_at,
        content=content,
    )


class _ActiveUniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_active_mapping(
    loader: _ActiveUniqueKeyLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise MemoryInvariantError(f"Duplicate Active Memory frontmatter key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_ActiveUniqueKeyLoader.add_constructor(
    BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_active_mapping,
)


def _non_empty(value: object, owner: str) -> None:
    if not isinstance(value, str) or not value:
        raise MemoryContractError(f"Memory {owner} must be non-empty text")


def _optional_text(value: object, owner: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise MemoryContractError(f"Memory patch {owner} must be text")
    return value
