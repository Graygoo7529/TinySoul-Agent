"""Current Business Day explicit Memory.md ownership."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from threading import RLock
from typing import cast

import yaml
from yaml.resolver import BaseResolver

from tinysoul.infra.filesystem import atomic_write_text, read_text_prefix

from ..errors import MemoryContractError, MemoryIOError, MemoryInvariantError


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
    updated_at: datetime | None
    content: str

    def __post_init__(self) -> None:
        if not isinstance(self.day, date):
            raise MemoryContractError("Active Memory day must be a date")
        if self.updated_at is not None and (
            not isinstance(self.updated_at, datetime) or self.updated_at.tzinfo is None
        ):
            raise MemoryContractError("Active Memory updated_at must include timezone")
        if not isinstance(self.content, str):
            raise MemoryContractError("Active Memory content must be text")


class ActiveMemoryStore:
    """Own the fixed Memory.md file under an injected Session root."""

    def __init__(self, *, session_root: Path, max_chars: int) -> None:
        if not isinstance(session_root, Path):
            raise MemoryContractError("Active Memory Session root must be a path")
        if (
            isinstance(max_chars, bool)
            or not isinstance(max_chars, int)
            or max_chars <= 0
        ):
            raise MemoryContractError("Active Memory limit must be positive")
        self._session_root = session_root
        self._max_chars = max_chars
        self._lock = RLock()

    @property
    def session_root(self) -> Path:
        return self._session_root

    @property
    def path(self) -> Path:
        return self._session_root / "Memory.md"

    def initialize_day(self, day: date) -> ActiveMemoryDocument:
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
            updated_at=None,
            content="",
        )
        return self._write(document)

    def read(self, expected_day: date | None = None) -> ActiveMemoryDocument:
        return self.read_from_root(self._session_root, expected_day=expected_day)

    def read_from_root(
        self,
        root: Path,
        *,
        expected_day: date | None = None,
    ) -> ActiveMemoryDocument:
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
        return document

    def patch(
        self,
        *,
        day: date,
        operations: Sequence[MemoryPatchOperation],
    ) -> ActiveMemoryDocument:
        operations = tuple(operations)
        if not operations:
            raise MemoryContractError("Memory patch requires operations")
        if any(not isinstance(item, MemoryPatchOperation) for item in operations):
            raise MemoryContractError("Memory patch operations are invalid")
        with self._lock:
            current = self.read(day)
            content = current.content
            for operation in operations:
                content = _apply_operation(content, operation)
            if len(content) > self._max_chars:
                raise MemoryContractError("Active Memory content exceeds its limit")
            if content == current.content:
                raise MemoryContractError("Memory patch did not change content")
            document = ActiveMemoryDocument(
                day=day,
                updated_at=datetime.now(UTC),
                content=content,
            )
            return self._write(document)

    def _write(self, document: ActiveMemoryDocument) -> ActiveMemoryDocument:
        text = _render_active(document)
        try:
            atomic_write_text(self.path, text)
        except OSError as exc:
            raise MemoryIOError(f"Failed to write Active Memory: {exc}") from exc
        return document


def _apply_operation(content: str, operation: MemoryPatchOperation) -> str:
    if operation.kind is MemoryPatchKind.APPEND:
        if not content:
            return operation.text.strip()
        return f"{content.rstrip()}\n\n{operation.text.strip()}"
    if operation.kind is MemoryPatchKind.CLEAR:
        return ""
    needle = (
        operation.old_text
        if operation.kind is MemoryPatchKind.REPLACE
        else operation.text
    )
    count = content.count(needle)
    if count != 1:
        raise MemoryContractError("Memory patch target must occur exactly once")
    if operation.kind is MemoryPatchKind.REPLACE:
        return content.replace(needle, operation.new_text, 1)
    return content.replace(needle, "", 1).strip()


def _render_active(document: ActiveMemoryDocument) -> str:
    metadata = {
        "schema_version": 2,
        "kind": "active",
        "day": document.day.isoformat(),
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
    expected = {"schema_version", "kind", "day", "updated_at"}
    if set(values) != expected:
        raise MemoryInvariantError("Active Memory frontmatter fields are invalid")
    if values.get("schema_version") != 2 or values.get("kind") != "active":
        raise MemoryInvariantError("Active Memory schema or kind is invalid")
    raw_day = values.get("day")
    if not isinstance(raw_day, str):
        raise MemoryInvariantError("Active Memory day must be text")
    try:
        day = date.fromisoformat(raw_day)
    except ValueError as exc:
        raise MemoryInvariantError("Active Memory day is invalid") from exc
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
            raise MemoryInvariantError(
                f"Duplicate Active Memory frontmatter key: {key}"
            )
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
