"""Crash-recoverable multi-document Memory changesets."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import shutil
from typing import cast
from uuid import uuid4

from tinysoul.infra.filesystem import atomic_write_text, read_text_prefix

from .documents import (
    DailyMemoryDocument,
    MemoryDocumentCodec,
    PersistentMemoryDocument,
)
from .errors import MemoryContractError, MemoryError, MemoryIOError, MemoryInvariantError
from .links import MemoryKind, MemoryLink
from .store import MemoryStore


@dataclass(frozen=True)
class MemoryDocumentChange:
    document: PersistentMemoryDocument
    expected_digest: str | None = None
    expected_absent: bool = False

    def __post_init__(self) -> None:
        if self.expected_absent and self.expected_digest is not None:
            raise MemoryContractError(
                "Memory change cannot expect both absent and a digest"
            )

    @property
    def link(self) -> MemoryLink:
        return self.document.link


@dataclass(frozen=True)
class MemoryChangeSet:
    transaction_id: str
    target_day: date
    base_generation: str
    changes: tuple[MemoryDocumentChange, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.transaction_id, str) or not self.transaction_id:
            raise MemoryContractError("Memory transaction id is invalid")
        if not isinstance(self.target_day, date):
            raise MemoryContractError("Memory changeset target day is invalid")
        if not isinstance(self.base_generation, str) or not self.base_generation:
            raise MemoryContractError("Memory changeset generation is invalid")
        changes = tuple(self.changes)
        if not changes or any(not isinstance(item, MemoryDocumentChange) for item in changes):
            raise MemoryContractError("Memory changeset requires document changes")
        links = tuple(item.link for item in changes)
        if len(set(links)) != len(links):
            raise MemoryContractError("Memory changeset Links must be unique")
        for change in changes:
            document = change.document
            if document.updated_on != self.target_day:
                raise MemoryContractError(
                    "Memory change updated_on must equal the target day"
                )
            if change.expected_absent and document.created_on != self.target_day:
                raise MemoryContractError(
                    "New Memory change created_on must equal the target day"
                )
            if (
                isinstance(document, DailyMemoryDocument)
                and document.day != self.target_day
            ):
                raise MemoryContractError(
                    "Daily Memory change day must equal the target day"
                )
        object.__setattr__(self, "changes", changes)

    @classmethod
    def create(
        cls,
        *,
        target_day: date,
        base_generation: str,
        changes: tuple[MemoryDocumentChange, ...],
    ) -> "MemoryChangeSet":
        return cls(
            transaction_id=f"memory_{uuid4().hex}",
            target_day=target_day,
            base_generation=base_generation,
            changes=changes,
        )


@dataclass(frozen=True)
class MemoryCommitOutcome:
    transaction_id: str
    changed_links: tuple[MemoryLink, ...]
    document_digests: dict[str, str]


@dataclass(frozen=True)
class _PreparedOperation:
    link: MemoryLink
    staged: str
    new_digest: str
    already_applied: bool


class MemoryTransactionService:
    """Prepare, commit, and roll forward deterministic Markdown replacements."""

    def __init__(self, *, store: MemoryStore, codec: MemoryDocumentCodec) -> None:
        self._store = store
        self._codec = codec
        self._root = store.internal_root / "transactions"

    def commit(
        self,
        changeset: MemoryChangeSet,
        *,
        current_generation: str,
    ) -> MemoryCommitOutcome:
        if changeset.base_generation != current_generation:
            raise MemoryContractError("Memory changeset catalog generation is stale")
        directory = self._prepare(changeset)
        return self._apply(directory)

    def recover(self) -> tuple[MemoryCommitOutcome, ...]:
        if not self._root.exists():
            return ()
        if self._root.is_symlink() or not self._root.is_dir():
            raise MemoryInvariantError("Memory transaction root is invalid")
        outcomes: list[MemoryCommitOutcome] = []
        for directory in sorted(self._root.iterdir(), key=lambda item: item.name):
            if directory.is_symlink() or not directory.is_dir():
                raise MemoryInvariantError("Memory transaction entry is invalid")
            outcomes.append(self._apply(directory))
        return tuple(outcomes)

    def _prepare(self, changeset: MemoryChangeSet) -> Path:
        directory = self._root / changeset.transaction_id
        if directory.exists():
            raise MemoryInvariantError("Memory transaction id already exists")
        staged = directory / "staged"
        try:
            staged.mkdir(parents=True, exist_ok=False)
            operations: list[dict[str, object]] = []
            ordered = sorted(
                changeset.changes,
                key=lambda item: (item.link.kind is MemoryKind.DAILY, str(item.link)),
            )
            for index, change in enumerate(ordered):
                stored = self._codec.stored(change.document)
                if len(stored.text) > self._store.max_chars(change.link.kind):
                    raise MemoryContractError(f"Memory change exceeds limit: {change.link}")
                operation_id = f"{index:04d}"
                atomic_write_text(staged / f"{operation_id}.md", stored.text)
                operations.append(
                    {
                        "operation_id": operation_id,
                        "link": str(change.link),
                        "expected_digest": change.expected_digest,
                        "expected_absent": change.expected_absent,
                        "new_digest": stored.digest,
                    }
                )
            manifest = {
                "schema_version": 1,
                "transaction_id": changeset.transaction_id,
                "target_day": changeset.target_day.isoformat(),
                "base_generation": changeset.base_generation,
                "operations": operations,
            }
            atomic_write_text(
                directory / "manifest.json",
                json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            )
        except (MemoryError, OSError):
            shutil.rmtree(directory, ignore_errors=True)
            raise
        return directory

    def _apply(self, directory: Path) -> MemoryCommitOutcome:
        manifest = self._manifest(directory)
        transaction_id = _text(manifest, "transaction_id")
        if transaction_id != directory.name:
            raise MemoryInvariantError("Memory transaction directory identity is invalid")
        target_day = _canonical_date(_text(manifest, "target_day"))
        base_generation = _text(manifest, "base_generation")
        if len(base_generation) != 24 or any(
            character not in "0123456789abcdef" for character in base_generation
        ):
            raise MemoryInvariantError("Memory transaction generation is invalid")
        operations = manifest.get("operations")
        if not isinstance(operations, list) or not operations:
            raise MemoryInvariantError("Memory transaction operations are invalid")
        staged_root = directory / "staged"
        if staged_root.is_symlink() or not staged_root.is_dir():
            raise MemoryInvariantError("Memory transaction staged root is invalid")
        prepared: list[_PreparedOperation] = []
        operation_ids: set[str] = set()
        operation_links: set[MemoryLink] = set()
        for index, raw in enumerate(operations):
            if not isinstance(raw, dict):
                raise MemoryInvariantError("Memory transaction operation is invalid")
            operation = cast(Mapping[str, object], raw)
            if set(operation) != {
                "operation_id",
                "link",
                "expected_digest",
                "expected_absent",
                "new_digest",
            }:
                raise MemoryInvariantError("Memory transaction operation fields are invalid")
            operation_id = _text(operation, "operation_id")
            if (
                len(operation_id) != 4
                or not operation_id.isascii()
                or not operation_id.isdigit()
                or operation_id != f"{index:04d}"
                or operation_id in operation_ids
            ):
                raise MemoryInvariantError("Memory transaction operation id is invalid")
            operation_ids.add(operation_id)
            link = MemoryLink.parse(_text(operation, "link"))
            if link in operation_links:
                raise MemoryInvariantError("Memory transaction Links are not unique")
            operation_links.add(link)
            expected_digest = raw.get("expected_digest")
            expected_absent = raw.get("expected_absent")
            new_digest = _text(operation, "new_digest")
            if expected_digest is not None and (
                not isinstance(expected_digest, str)
                or not _is_digest(expected_digest)
            ):
                raise MemoryInvariantError("Memory transaction expected digest is invalid")
            if not isinstance(expected_absent, bool):
                raise MemoryInvariantError("Memory transaction expected_absent is invalid")
            if expected_absent and expected_digest is not None:
                raise MemoryInvariantError("Memory transaction CAS fields conflict")
            if not _is_digest(new_digest):
                raise MemoryInvariantError("Memory transaction new digest is invalid")
            staged_path = directory / "staged" / f"{operation_id}.md"
            staged = _read_bounded(staged_path, self._store.max_chars(link.kind))
            if sha256(staged.encode("utf-8")).hexdigest() != new_digest:
                raise MemoryInvariantError("Memory staged digest is invalid")
            document = self._codec.parse(link, staged)
            if document.updated_on != target_day:
                raise MemoryInvariantError(
                    "Memory transaction document updated_on differs from target day"
                )
            if expected_absent and document.created_on != target_day:
                raise MemoryInvariantError(
                    "New Memory transaction document created_on differs from target day"
                )
            if (
                isinstance(document, DailyMemoryDocument)
                and document.day != target_day
            ):
                raise MemoryInvariantError(
                    "Daily Memory transaction day differs from target day"
                )
            target = self._store.validate_write_target(link)
            current_digest = (
                _file_digest(target, max_chars=self._store.max_chars(link.kind))
                if target.is_file()
                else None
            )
            already_applied = current_digest == new_digest
            if not already_applied and target.exists() and not target.is_file():
                raise MemoryInvariantError("Memory transaction target is not a file")
            if not already_applied and expected_absent:
                if current_digest is not None:
                    raise MemoryInvariantError("Memory transaction absent CAS failed")
            elif not already_applied and expected_digest is not None:
                if current_digest != expected_digest:
                    raise MemoryInvariantError("Memory transaction digest CAS failed")
            elif not already_applied:
                raise MemoryInvariantError("Memory transaction operation lacks CAS")
            prepared.append(
                _PreparedOperation(
                    link=link,
                    staged=staged,
                    new_digest=new_digest,
                    already_applied=already_applied,
                )
            )
        seen_daily = False
        for operation in prepared:
            if operation.link.kind is MemoryKind.DAILY:
                seen_daily = True
            elif seen_daily:
                raise MemoryInvariantError(
                    "Memory transaction must apply daily documents last"
                )

        # Validate every staged document and every CAS before the first write.
        changed: list[MemoryLink] = []
        digests: dict[str, str] = {}
        for operation in prepared:
            if not operation.already_applied:
                target = self._store.validate_write_target(operation.link)
                try:
                    atomic_write_text(target, operation.staged)
                except OSError as exc:
                    raise MemoryIOError(f"Memory transaction write failed: {exc}") from exc
            changed.append(operation.link)
            digests[str(operation.link)] = operation.new_digest
        try:
            shutil.rmtree(directory)
            if self._root.exists() and not any(self._root.iterdir()):
                self._root.rmdir()
        except OSError as exc:
            raise MemoryIOError(f"Memory transaction cleanup failed: {exc}") from exc
        return MemoryCommitOutcome(
            transaction_id=transaction_id,
            changed_links=tuple(changed),
            document_digests=digests,
        )

    @staticmethod
    def _manifest(directory: Path) -> dict[str, object]:
        path = directory / "manifest.json"
        if path.is_symlink() or not path.is_file():
            raise MemoryInvariantError("Memory transaction manifest is invalid")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MemoryInvariantError("Memory transaction manifest is invalid") from exc
        if (
            not isinstance(value, dict)
            or set(value) != {
                "schema_version",
                "transaction_id",
                "target_day",
                "base_generation",
                "operations",
            }
            or value.get("schema_version") != 1
        ):
            raise MemoryInvariantError("Memory transaction schema is invalid")
        return cast(dict[str, object], value)


def _read_bounded(path: Path, max_chars: int) -> str:
    if path.is_symlink() or not path.is_file():
        raise MemoryInvariantError("Memory staged document is invalid")
    try:
        read = read_text_prefix(path, max_chars=max_chars)
    except (OSError, UnicodeDecodeError) as exc:
        raise MemoryInvariantError("Memory staged document is unreadable") from exc
    if read.truncated:
        raise MemoryInvariantError("Memory staged document exceeds limit")
    return read.text


def _file_digest(path: Path, *, max_chars: int) -> str:
    return sha256(_read_bounded(path, max_chars).encode("utf-8")).hexdigest()


def _text(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise MemoryInvariantError(f"Memory transaction {key} is invalid")
    return item


def _canonical_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise MemoryInvariantError("Memory transaction target day is invalid") from exc
    if parsed.isoformat() != value:
        raise MemoryInvariantError("Memory transaction target day is not canonical")
    return parsed


def _is_digest(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )
