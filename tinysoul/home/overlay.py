"""Persistent effective overlay for the mutable Agent Home working copy."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from enum import StrEnum
import json
import os
from pathlib import Path, PurePosixPath
import shutil
from threading import RLock
from uuid import uuid4

from tinysoul.infra.filesystem import (
    FilesystemBoundaryError,
    atomic_copy_file,
    atomic_write_text,
    resolve_under_root,
)
from tinysoul.infra.json import JsonObject, to_json_object
from .errors import AgentHomeContractError, AgentHomeIOError, AgentHomeInvariantError


class HomeOverlayState(StrEnum):
    COPIED = "copied"
    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"


@dataclass(frozen=True)
class HomeOverlayRecord:
    relative_path: str
    state: HomeOverlayState
    baseline_digest: str = ""
    runtime_digest: str = ""
    size: int = 0
    mtime_ns: int = 0

    def __post_init__(self) -> None:
        _validate_relative_path(self.relative_path)
        if not isinstance(self.state, HomeOverlayState):
            raise AgentHomeContractError("Home overlay state is invalid")
        if not isinstance(self.baseline_digest, str) or not isinstance(
            self.runtime_digest, str
        ):
            raise AgentHomeContractError("Home overlay digests must be strings")
        if self.state is HomeOverlayState.DELETED:
            if self.runtime_digest or self.size or self.mtime_ns:
                raise AgentHomeContractError(
                    "Deleted Home overlay records cannot describe runtime content"
                )
        elif not self.runtime_digest:
            raise AgentHomeContractError(
                "Active Home overlay records require a runtime digest"
            )
        if self.state is HomeOverlayState.CREATED and self.baseline_digest:
            raise AgentHomeContractError(
                "Created Home overlay records cannot have a baseline digest"
            )
        if (
            self.state in {HomeOverlayState.COPIED, HomeOverlayState.MODIFIED}
            and not self.baseline_digest
        ):
            raise AgentHomeContractError(
                "Copied or modified Home overlay records require a baseline digest"
            )
        if self.state is HomeOverlayState.COPIED and self.runtime_digest != self.baseline_digest:
            raise AgentHomeContractError(
                "Copied Home overlay content must equal its baseline"
            )
        if isinstance(self.size, bool) or not isinstance(self.size, int) or self.size < 0:
            raise AgentHomeContractError("Home overlay size must be non-negative")
        if (
            isinstance(self.mtime_ns, bool)
            or not isinstance(self.mtime_ns, int)
            or self.mtime_ns < 0
        ):
            raise AgentHomeContractError("Home overlay mtime_ns must be non-negative")

    def to_json(self) -> JsonObject:
        return {
            "relative_path": self.relative_path,
            "state": self.state.value,
            "baseline_digest": self.baseline_digest,
            "runtime_digest": self.runtime_digest,
            "size": self.size,
            "mtime_ns": self.mtime_ns,
        }

    @classmethod
    def from_json(cls, value: JsonObject) -> "HomeOverlayRecord":
        try:
            state = HomeOverlayState(_required_str(value, "state"))
        except ValueError as exc:
            raise AgentHomeContractError("Unknown Home overlay state") from exc
        return cls(
            relative_path=_required_str(value, "relative_path"),
            state=state,
            baseline_digest=_optional_str(value, "baseline_digest"),
            runtime_digest=_optional_str(value, "runtime_digest"),
            size=_non_negative_int(value, "size"),
            mtime_ns=_non_negative_int(value, "mtime_ns"),
        )


@dataclass(frozen=True)
class HomeOverlayManifest:
    revision: int = 0
    records: tuple[HomeOverlayRecord, ...] = field(default_factory=tuple)
    schema_version: int = 2

    def __post_init__(self) -> None:
        if self.schema_version != 2:
            raise AgentHomeContractError("Home overlay schema_version must be 2")
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 0
        ):
            raise AgentHomeContractError("Home overlay revision must be non-negative")
        records = tuple(self.records)
        if any(not isinstance(record, HomeOverlayRecord) for record in records):
            raise AgentHomeContractError(
                "Home overlay records must contain HomeOverlayRecord values"
            )
        object.__setattr__(self, "records", records)
        paths = tuple(record.relative_path for record in records)
        if len(paths) != len(set(paths)):
            raise AgentHomeContractError("Home overlay paths must be unique")

    def to_json(self) -> JsonObject:
        return {
            "schema_version": self.schema_version,
            "revision": self.revision,
            "records": [record.to_json() for record in self.records],
        }

    @classmethod
    def from_json(cls, value: JsonObject) -> "HomeOverlayManifest":
        schema_version = _non_negative_int(value, "schema_version")
        if schema_version not in {1, 2}:
            raise AgentHomeContractError("Home overlay schema_version must be 1 or 2")
        if schema_version == 1:
            legacy_day = _required_str(value, "day")
            try:
                date.fromisoformat(legacy_day)
            except ValueError as exc:
                raise AgentHomeContractError(
                    "Legacy Home overlay day must be an ISO date"
                ) from exc
        records_value = value.get("records", [])
        if not isinstance(records_value, list):
            raise AgentHomeContractError("Home overlay records must be a list")
        records: list[HomeOverlayRecord] = []
        for item in records_value:
            if not isinstance(item, dict):
                raise AgentHomeContractError("Home overlay records must be objects")
            records.append(HomeOverlayRecord.from_json(to_json_object(item)))
        return cls(
            revision=_non_negative_int(value, "revision"),
            records=tuple(records),
        )

    def record_for(self, relative_path: str) -> HomeOverlayRecord | None:
        return next(
            (record for record in self.records if record.relative_path == relative_path),
            None,
        )

    def with_record(self, record: HomeOverlayRecord) -> "HomeOverlayManifest":
        records = {
            existing.relative_path: existing
            for existing in self.records
        }
        records[record.relative_path] = record
        return replace(
            self,
            revision=self.revision + 1,
            records=tuple(records[path] for path in sorted(records)),
        )

    def without_record(self, relative_path: str) -> "HomeOverlayManifest":
        if self.record_for(relative_path) is None:
            return self
        return replace(
            self,
            revision=self.revision + 1,
            records=tuple(
                record
                for record in self.records
                if record.relative_path != relative_path
            ),
        )


@dataclass(frozen=True)
class EffectiveHomeResource:
    relative_path: str
    path: Path
    digest: str
    state: HomeOverlayState
    baseline_digest: str = ""


@dataclass(frozen=True)
class HomeOverlayOperation:
    operation_id: str
    relative_path: str
    before: HomeOverlayRecord | None
    after: HomeOverlayRecord

    def __post_init__(self) -> None:
        if (
            not isinstance(self.operation_id, str)
            or not self.operation_id.startswith("op_")
            or not self.operation_id.replace("_", "").isalnum()
        ):
            raise AgentHomeContractError("Home operation id is invalid")
        if self.before is not None and not isinstance(
            self.before, HomeOverlayRecord
        ):
            raise AgentHomeContractError(
                "Home operation before must be a HomeOverlayRecord"
            )
        if not isinstance(self.after, HomeOverlayRecord):
            raise AgentHomeContractError(
                "Home operation after must be a HomeOverlayRecord"
            )
        _validate_relative_path(self.relative_path)
        if self.relative_path != self.after.relative_path or (
            self.before is not None
            and self.before.relative_path != self.relative_path
        ):
            raise AgentHomeContractError("Home operation paths do not match")

    def to_json(self) -> JsonObject:
        return {
            "schema_version": 1,
            "operation_id": self.operation_id,
            "relative_path": self.relative_path,
            "before": self.before.to_json() if self.before is not None else None,
            "after": self.after.to_json(),
        }

    @classmethod
    def from_json(cls, value: JsonObject) -> "HomeOverlayOperation":
        if _non_negative_int(value, "schema_version") != 1:
            raise AgentHomeContractError("Home operation schema_version must be 1")
        before_value = value.get("before")
        after_value = value.get("after")
        if before_value is not None and not isinstance(before_value, dict):
            raise AgentHomeContractError("Home operation before must be an object")
        if not isinstance(after_value, dict):
            raise AgentHomeContractError("Home operation after must be an object")
        operation = cls(
            operation_id=_required_str(value, "operation_id"),
            relative_path=_required_str(value, "relative_path"),
            before=(
                HomeOverlayRecord.from_json(to_json_object(before_value))
                if isinstance(before_value, dict)
                else None
            ),
            after=HomeOverlayRecord.from_json(to_json_object(after_value)),
        )
        return operation


class HomeOverlayStore:
    def __init__(self, runtime_root: Path) -> None:
        self.runtime_root = runtime_root
        self.metadata_root = runtime_root / ".tinysoul"
        self.manifest_path = self.metadata_root / "home_overlay.json"
        self.operations_root = self.metadata_root / "operations"

    def load(self) -> HomeOverlayManifest | None:
        if not self.manifest_path.exists():
            return None
        value = _read_object(self.manifest_path, label="overlay manifest")
        try:
            manifest = HomeOverlayManifest.from_json(value)
        except AgentHomeContractError as exc:
            raise AgentHomeInvariantError(
                f"Persisted Home overlay manifest is invalid: {exc}"
            ) from exc
        if value.get("schema_version") == 1:
            self.save(manifest)
        return manifest

    def save(self, manifest: HomeOverlayManifest) -> None:
        _write_object(self.manifest_path, manifest.to_json())

    def prepare_operation(
        self,
        operation: HomeOverlayOperation,
        *,
        content: bytes | None,
    ) -> Path:
        if content is None and operation.after.state is not HomeOverlayState.DELETED:
            raise AgentHomeContractError(
                "Active Home operation requires staged content"
            )
        directory = self.operations_root / operation.operation_id
        try:
            directory.mkdir(parents=True, exist_ok=False)
            if content is not None:
                (directory / "after").write_bytes(content)
            _write_object(directory / "operation.json", operation.to_json())
        except OSError as exc:
            raise AgentHomeIOError(f"Failed to prepare Home operation: {exc}") from exc
        return directory

    def operations(self) -> tuple[tuple[HomeOverlayOperation, Path], ...]:
        if not self.operations_root.exists():
            return ()
        result: list[tuple[HomeOverlayOperation, Path]] = []
        for directory in sorted(self.operations_root.iterdir(), key=lambda item: item.name):
            if not directory.is_dir():
                raise AgentHomeInvariantError(
                    f"Home operation entry is not a directory: {directory}"
                )
            operation_path = directory / "operation.json"
            if not operation_path.exists():
                self.discard_operation(directory)
                continue
            value = _read_object(operation_path, label="operation")
            try:
                operation = HomeOverlayOperation.from_json(value)
            except AgentHomeContractError as exc:
                raise AgentHomeInvariantError(
                    f"Persisted Home operation is invalid: {exc}"
                ) from exc
            if operation.operation_id != directory.name:
                raise AgentHomeInvariantError("Home operation directory identity mismatch")
            result.append((operation, directory))
        return tuple(result)

    @staticmethod
    def discard_operation(directory: Path) -> None:
        try:
            shutil.rmtree(directory)
        except OSError as exc:
            raise AgentHomeIOError(f"Failed to finalize Home operation: {exc}") from exc


class HomeOverlayManager:
    """Serialize cross-day Home mirror reads, writes, and recovery."""

    def __init__(self, *, original_root: Path, runtime_root: Path) -> None:
        self._original_root = original_root
        self._runtime_root = runtime_root
        self._store = HomeOverlayStore(runtime_root)
        self._lock = RLock()

    def initialize(self) -> HomeOverlayManifest:
        with self._lock:
            manifest = self._store.load()
            if manifest is not None:
                return self._reconcile(manifest)
            records = self._legacy_records()
            manifest = HomeOverlayManifest(records=records)
            self._store.save(manifest)
            return self._reconcile(manifest)

    def reconcile(self) -> HomeOverlayManifest:
        with self._lock:
            return self._reconcile(self._require_manifest())

    def records(self) -> tuple[HomeOverlayRecord, ...]:
        with self._lock:
            return self._reconcile(self._require_manifest()).records

    def record_for(self, relative_path: str) -> HomeOverlayRecord | None:
        with self._lock:
            _validate_relative_path(relative_path)
            return self._reconcile(self._require_manifest()).record_for(relative_path)

    def clear_record(self, relative_path: str) -> bool:
        """Remove one processed overlay record without encoding review state."""

        with self._lock:
            _validate_relative_path(relative_path)
            manifest = self._reconcile(self._require_manifest())
            record = manifest.record_for(relative_path)
            if record is None:
                return False
            self._store.save(manifest.without_record(relative_path))
            if record.state is not HomeOverlayState.DELETED:
                target = self._runtime_path(relative_path)
                try:
                    target.unlink(missing_ok=True)
                    _prune_empty_parents(target.parent, stop=self._runtime_root)
                except OSError as exc:
                    raise AgentHomeIOError(
                        f"Failed to clear processed runtime Home content: {exc}"
                    ) from exc
            return True

    def effective(self, relative_path: str) -> EffectiveHomeResource | None:
        with self._lock:
            _validate_relative_path(relative_path)
            manifest = self._reconcile(self._require_manifest())
            record = manifest.record_for(relative_path)
            if record is not None:
                if record.state is HomeOverlayState.DELETED:
                    return None
                runtime = self._runtime_path(relative_path)
                return EffectiveHomeResource(
                    relative_path=relative_path,
                    path=runtime,
                    digest=record.runtime_digest,
                    state=record.state,
                    baseline_digest=record.baseline_digest,
                )
            return None

    def is_deleted(self, relative_path: str) -> bool:
        with self._lock:
            manifest = self._reconcile(self._require_manifest())
            record = manifest.record_for(relative_path)
            return record is not None and record.state is HomeOverlayState.DELETED

    def ensure_copy(self, relative_path: str) -> EffectiveHomeResource:
        with self._lock:
            existing = self.effective(relative_path)
            if existing is not None:
                return existing
            manifest = self._require_manifest()
            deleted = manifest.record_for(relative_path)
            if deleted is not None and deleted.state is HomeOverlayState.DELETED:
                raise AgentHomeContractError(
                    f"Home resource was deleted in the active overlay: {relative_path}"
                )
            source = self._source_path(relative_path)
            if not source.is_file() or source.is_symlink():
                raise AgentHomeContractError(
                    f"Home source is not a regular file: {source}"
                )
            content = _read_bytes(source)
            digest = _digest_bytes(content)
            after = _record_from_content(
                relative_path,
                content,
                baseline_digest=digest,
            )
            self._commit(manifest, before=None, after=after, content=content)
            result = self.effective(relative_path)
            if result is None:
                raise AgentHomeInvariantError("Home copy did not become effective")
            return result

    def reset_to_actual_copy(self, relative_path: str) -> HomeOverlayRecord:
        """Replace any overlay state with a fresh copy of current actual content."""

        with self._lock:
            _validate_relative_path(relative_path)
            manifest = self._reconcile(self._require_manifest())
            source = self._source_path(relative_path)
            if not source.is_file() or source.is_symlink():
                raise AgentHomeContractError(
                    f"Home source is not a regular file: {source}"
                )
            content = _read_bytes(source)
            digest = _digest_bytes(content)
            after = _record_from_content(
                relative_path,
                content,
                baseline_digest=digest,
            )
            return self._commit(
                manifest,
                before=manifest.record_for(relative_path),
                after=after,
                content=content,
            )

    def write(
        self,
        relative_path: str,
        text: str,
        *,
        overwrite: bool,
        expected_digest: str,
    ) -> HomeOverlayRecord:
        with self._lock:
            if not isinstance(text, str):
                raise AgentHomeContractError("Home write text must be a string")
            if not isinstance(overwrite, bool):
                raise AgentHomeContractError("Home overwrite must be a boolean")
            if not isinstance(expected_digest, str):
                raise AgentHomeContractError("Home expected_digest must be a string")
            _validate_relative_path(relative_path)
            manifest = self._reconcile(self._require_manifest())
            before = manifest.record_for(relative_path)
            current = self._effective_digest(relative_path, manifest)
            if current and not overwrite:
                raise AgentHomeContractError(
                    f"Home resource already exists: {relative_path}"
                )
            if expected_digest and current != expected_digest:
                raise AgentHomeContractError(
                    f"Home resource digest mismatch: {relative_path}"
                )
            source = self._source_path(relative_path)
            baseline = before.baseline_digest if before is not None else ""
            if not baseline and source.is_file() and not source.is_symlink():
                baseline = _file_digest(source)
            content = text.encode("utf-8")
            after = _record_from_content(
                relative_path,
                content,
                baseline_digest=baseline,
            )
            return self._commit(
                manifest,
                before=before,
                after=after,
                content=content,
            )

    def patch(
        self,
        relative_path: str,
        *,
        old_text: str,
        new_text: str,
        expected_digest: str,
        max_chars: int,
    ) -> HomeOverlayRecord:
        with self._lock:
            if not isinstance(old_text, str) or not old_text:
                raise AgentHomeContractError("Home patch old_text must be non-empty")
            if not isinstance(new_text, str):
                raise AgentHomeContractError("Home patch new_text must be a string")
            if not isinstance(expected_digest, str):
                raise AgentHomeContractError(
                    "Home patch expected_digest must be a string"
                )
            if (
                isinstance(max_chars, bool)
                or not isinstance(max_chars, int)
                or max_chars <= 0
            ):
                raise AgentHomeContractError(
                    "Home patch max_chars must be positive"
                )
            effective = self.effective(relative_path)
            if effective is None:
                effective = self.ensure_copy(relative_path)
            if expected_digest and effective.digest != expected_digest:
                raise AgentHomeContractError(
                    f"Home resource digest mismatch: {relative_path}"
                )
            try:
                current = effective.path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise AgentHomeIOError(f"Failed to read Home patch target: {exc}") from exc
            count = current.count(old_text)
            if count != 1:
                detail = "not found" if count == 0 else "not unique"
                raise AgentHomeContractError(
                    f"Home patch old_text is {detail}: {relative_path}"
                )
            updated = current.replace(old_text, new_text, 1)
            if len(updated) > max_chars:
                raise AgentHomeContractError(
                    f"Home patch exceeds {max_chars} characters"
                )
            return self.write(
                relative_path,
                updated,
                overwrite=True,
                expected_digest=effective.digest,
            )

    def delete(self, relative_path: str, *, expected_digest: str) -> HomeOverlayRecord:
        with self._lock:
            if not isinstance(expected_digest, str):
                raise AgentHomeContractError(
                    "Home delete expected_digest must be a string"
                )
            manifest = self._reconcile(self._require_manifest())
            before = manifest.record_for(relative_path)
            current = self._effective_digest(relative_path, manifest)
            if not current:
                raise AgentHomeContractError(
                    f"Home resource does not exist: {relative_path}"
                )
            if expected_digest and expected_digest != current:
                raise AgentHomeContractError(
                    f"Home resource digest mismatch: {relative_path}"
                )
            source = self._source_path(relative_path)
            baseline = before.baseline_digest if before is not None else ""
            if not baseline and source.is_file() and not source.is_symlink():
                baseline = _file_digest(source)
            after = HomeOverlayRecord(
                relative_path=relative_path,
                state=HomeOverlayState.DELETED,
                baseline_digest=baseline,
            )
            return self._commit(
                manifest,
                before=before,
                after=after,
                content=None,
            )

    def _reconcile(self, manifest: HomeOverlayManifest) -> HomeOverlayManifest:
        manifest = self._recover_operations(manifest)
        records = {record.relative_path: record for record in manifest.records}
        disk = self._runtime_files()
        changed = False
        for relative_path, record in tuple(records.items()):
            path = disk.pop(relative_path, None)
            if record.state is HomeOverlayState.DELETED:
                if path is not None:
                    raise AgentHomeInvariantError(
                        f"Deleted Home overlay path reappeared: {relative_path}"
                    )
                continue
            if path is None:
                if record.state is HomeOverlayState.COPIED:
                    source = self._source_path(relative_path)
                    if source.is_file() and _file_digest(source) == record.baseline_digest:
                        try:
                            atomic_copy_file(source, self._runtime_path(relative_path))
                        except OSError as exc:
                            raise AgentHomeIOError(
                                f"Failed to restore Home copy: {exc}"
                            ) from exc
                        path = self._runtime_path(relative_path)
                    else:
                        raise AgentHomeInvariantError(
                            f"Home copied source changed after runtime loss: {relative_path}"
                        )
                else:
                    raise AgentHomeInvariantError(
                        f"Home runtime content disappeared: {relative_path}"
                    )
            current = _record_for_path(
                relative_path,
                path,
                baseline_digest=record.baseline_digest,
            )
            if current != record:
                records[relative_path] = current
                changed = True
        for relative_path, path in disk.items():
            source = self._source_path(relative_path)
            baseline = (
                _file_digest(source)
                if source.is_file() and not source.is_symlink()
                else ""
            )
            records[relative_path] = _record_for_path(
                relative_path,
                path,
                baseline_digest=baseline,
            )
            changed = True
        if not changed:
            return manifest
        reconciled = replace(
            manifest,
            revision=manifest.revision + 1,
            records=tuple(records[path] for path in sorted(records)),
        )
        self._store.save(reconciled)
        return reconciled

    def _recover_operations(
        self,
        manifest: HomeOverlayManifest,
    ) -> HomeOverlayManifest:
        current = manifest
        for operation, directory in self._store.operations():
            recorded = current.record_for(operation.relative_path)
            target = self._runtime_path(operation.relative_path)
            if (
                _same_record_content(recorded, operation.after)
                and self._disk_matches(target, operation.after)
            ):
                self._store.discard_operation(directory)
                continue
            if not _same_record_content(recorded, operation.before):
                raise AgentHomeInvariantError(
                    f"Home operation manifest state is ambiguous: {operation.operation_id}"
                )
            self._apply_operation_file(operation, directory)
            current = current.with_record(self._applied_record(operation.after))
            self._store.save(current)
            self._store.discard_operation(directory)
        return current

    def _commit(
        self,
        manifest: HomeOverlayManifest,
        *,
        before: HomeOverlayRecord | None,
        after: HomeOverlayRecord,
        content: bytes | None,
    ) -> HomeOverlayRecord:
        operation = HomeOverlayOperation(
            operation_id=f"op_{uuid4().hex[:16]}",
            relative_path=after.relative_path,
            before=before,
            after=after,
        )
        directory = self._store.prepare_operation(operation, content=content)
        self._apply_operation_file(operation, directory)
        persisted = self._applied_record(after)
        self._store.save(manifest.with_record(persisted))
        self._store.discard_operation(directory)
        return persisted

    def _applied_record(self, intent: HomeOverlayRecord) -> HomeOverlayRecord:
        if intent.state is HomeOverlayState.DELETED:
            return intent
        record = _record_for_path(
            intent.relative_path,
            self._runtime_path(intent.relative_path),
            baseline_digest=intent.baseline_digest,
        )
        if not _same_record_content(record, intent):
            raise AgentHomeInvariantError(
                f"Home operation changed content identity: {intent.relative_path}"
            )
        return record

    def _apply_operation_file(
        self,
        operation: HomeOverlayOperation,
        directory: Path,
    ) -> None:
        target = self._runtime_path(operation.relative_path)
        if operation.after.state is HomeOverlayState.DELETED:
            try:
                target.unlink(missing_ok=True)
            except OSError as exc:
                raise AgentHomeIOError(f"Failed to delete runtime Home file: {exc}") from exc
            return
        staged = directory / "after"
        if staged.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.replace(staged, target)
            except OSError as exc:
                raise AgentHomeIOError(f"Failed to apply Home operation: {exc}") from exc
        if not self._disk_matches(target, operation.after):
            raise AgentHomeInvariantError(
                f"Home operation content does not match intent: {operation.operation_id}"
            )

    def _disk_matches(self, path: Path, record: HomeOverlayRecord) -> bool:
        if record.state is HomeOverlayState.DELETED:
            return not path.exists()
        return (
            path.is_file()
            and not path.is_symlink()
            and _file_digest(path) == record.runtime_digest
        )

    def _effective_digest(
        self,
        relative_path: str,
        manifest: HomeOverlayManifest,
    ) -> str:
        record = manifest.record_for(relative_path)
        if record is not None:
            return "" if record.state is HomeOverlayState.DELETED else record.runtime_digest
        source = self._source_path(relative_path)
        if source.is_file() and not source.is_symlink():
            return _file_digest(source)
        return ""

    def _legacy_records(self) -> tuple[HomeOverlayRecord, ...]:
        return tuple(
            _record_for_path(
                relative,
                path,
                baseline_digest=(
                    _file_digest(source)
                    if (source := self._source_path(relative)).is_file()
                    and not source.is_symlink()
                    else ""
                ),
            )
            for relative, path in sorted(self._runtime_files().items())
        )

    def _runtime_files(self) -> dict[str, Path]:
        if not self._runtime_root.exists():
            return {}
        if not self._runtime_root.is_dir():
            raise AgentHomeInvariantError("Runtime Home root is not a directory")
        result: dict[str, Path] = {}
        for path in self._runtime_root.rglob("*"):
            try:
                relative = path.relative_to(self._runtime_root).as_posix()
            except ValueError as exc:
                raise AgentHomeInvariantError("Runtime Home path escaped root") from exc
            if relative == ".tinysoul" or relative.startswith(".tinysoul/"):
                continue
            if path.is_symlink():
                raise AgentHomeInvariantError(
                    f"Runtime Home cannot contain symlinks: {relative}"
                )
            if path.is_file():
                result[relative] = path
            elif not path.is_dir():
                raise AgentHomeInvariantError(
                    f"Runtime Home contains unsupported entry: {relative}"
                )
        return result

    def _source_path(self, relative_path: str) -> Path:
        try:
            return resolve_under_root(self._original_root, relative_path)
        except FilesystemBoundaryError as exc:
            raise AgentHomeContractError(str(exc)) from exc

    def _runtime_path(self, relative_path: str) -> Path:
        try:
            return resolve_under_root(self._runtime_root, relative_path)
        except FilesystemBoundaryError as exc:
            raise AgentHomeContractError(str(exc)) from exc

    def _require_manifest(self) -> HomeOverlayManifest:
        manifest = self._store.load()
        if manifest is None:
            raise AgentHomeInvariantError("Home overlay is not initialized")
        return manifest


def _record_from_content(
    relative_path: str,
    content: bytes,
    *,
    baseline_digest: str,
) -> HomeOverlayRecord:
    runtime_digest = _digest_bytes(content)
    state = (
        HomeOverlayState.COPIED
        if baseline_digest and runtime_digest == baseline_digest
        else HomeOverlayState.MODIFIED
        if baseline_digest
        else HomeOverlayState.CREATED
    )
    return HomeOverlayRecord(
        relative_path=relative_path,
        state=state,
        baseline_digest=baseline_digest,
        runtime_digest=runtime_digest,
        size=len(content),
        mtime_ns=0,
    )


def _record_for_path(
    relative_path: str,
    path: Path,
    *,
    baseline_digest: str,
) -> HomeOverlayRecord:
    if not path.is_file() or path.is_symlink():
        raise AgentHomeInvariantError(f"Home runtime path is not a regular file: {path}")
    try:
        stat = path.stat()
    except OSError as exc:
        raise AgentHomeIOError(f"Failed to stat runtime Home file: {exc}") from exc
    digest = _file_digest(path)
    state = (
        HomeOverlayState.COPIED
        if baseline_digest and digest == baseline_digest
        else HomeOverlayState.MODIFIED
        if baseline_digest
        else HomeOverlayState.CREATED
    )
    return HomeOverlayRecord(
        relative_path=relative_path,
        state=state,
        baseline_digest=baseline_digest,
        runtime_digest=digest,
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
    )


def _same_record_content(
    left: HomeOverlayRecord | None,
    right: HomeOverlayRecord | None,
) -> bool:
    if left is None or right is None:
        return left is right
    return (
        left.relative_path == right.relative_path
        and left.state is right.state
        and left.baseline_digest == right.baseline_digest
        and left.runtime_digest == right.runtime_digest
    )


def _validate_relative_path(value: str) -> None:
    if not isinstance(value, str) or not value or "\\" in value:
        raise AgentHomeContractError("Home overlay path must be non-empty POSIX text")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise AgentHomeContractError(f"Invalid Home overlay path: {value}")
    if path.parts[0] == ".tinysoul":
        raise AgentHomeContractError("Home overlay path cannot target internal metadata")


def _digest_bytes(value: bytes) -> str:
    from hashlib import sha256

    return sha256(value).hexdigest()


def _file_digest(path: Path) -> str:
    from tinysoul.infra.filesystem import file_digest

    try:
        return file_digest(path)
    except OSError as exc:
        raise AgentHomeIOError(f"Failed to digest Home file: {exc}") from exc


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise AgentHomeIOError(f"Failed to read Home source: {exc}") from exc


def _read_object(path: Path, *, label: str) -> JsonObject:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AgentHomeIOError(f"Failed to read Home {label}: {exc}") from exc
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AgentHomeInvariantError(
            f"Persisted Home {label} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise AgentHomeInvariantError(f"Home {label} root must be an object")
    return to_json_object(value)


def _write_object(path: Path, value: JsonObject) -> None:
    try:
        atomic_write_text(
            path,
            json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        )
    except OSError as exc:
        raise AgentHomeIOError(f"Failed to write Home metadata: {exc}") from exc


def _prune_empty_parents(path: Path, *, stop: Path) -> None:
    current = path
    stop_resolved = stop.resolve()
    while current.resolve() != stop_resolved:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _required_str(value: JsonObject, name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item:
        raise AgentHomeContractError(f"Home field must be non-empty text: {name}")
    return item


def _optional_str(value: JsonObject, name: str) -> str:
    item = value.get(name, "")
    if not isinstance(item, str):
        raise AgentHomeContractError(f"Home field must be text: {name}")
    return item


def _non_negative_int(value: JsonObject, name: str) -> int:
    item = value.get(name, 0)
    if isinstance(item, bool) or not isinstance(item, int) or item < 0:
        raise AgentHomeContractError(f"Home field must be non-negative int: {name}")
    return item
