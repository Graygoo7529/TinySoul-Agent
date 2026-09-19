"""Persistent effective overlay for the mutable Agent Home working copy."""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import shutil
from threading import RLock
from uuid import uuid4

from tinysoul.infra.filesystem import (
    FilesystemBoundaryError,
    atomic_copy_file,
    resolve_under_root,
)
from ..errors import AgentHomeContractError, AgentHomeIOError, AgentHomeInvariantError


from .models import (
    HomeOverlayState,
    HomeOverlayRecord,
    HomeOverlayManifest,
    EffectiveHomeResource,
    HomeOverlayOperation,
    _validate_relative_path,
)
from .store import HomeOverlayStore
from .files import _digest_bytes, _file_digest, _read_bytes, _prune_empty_parents


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

    def remove_if_empty(self) -> bool:
        """Remove an empty runtime Home so the next access materializes it anew."""

        with self._lock:
            manifest = self._reconcile(self._require_manifest())
            if manifest.records or self._store.operations():
                return False
            self._validate_empty_overlay_root()
            cleared_root = self._runtime_root.with_name(
                f".{self._runtime_root.name}.cleared-{uuid4().hex}"
            )
            try:
                os.replace(self._runtime_root, cleared_root)
            except OSError as exc:
                raise AgentHomeIOError(
                    f"Failed to isolate empty runtime Home: {exc}"
                ) from exc
            try:
                shutil.rmtree(cleared_root)
            except OSError as exc:
                try:
                    os.replace(cleared_root, self._runtime_root)
                except OSError as rollback_error:
                    raise AgentHomeIOError(
                        "Failed to remove empty runtime Home and restore its root: "
                        f"{rollback_error}"
                    ) from exc
                raise AgentHomeIOError(
                    f"Failed to remove empty runtime Home: {exc}"
                ) from exc
            return True

    def _validate_empty_overlay_root(self) -> None:
        """Reject unowned content before removing the reconciled overlay root."""

        try:
            metadata_entries = set(self._store.metadata_root.iterdir())
            expected_metadata = {self._store.manifest_path}
            if self._store.operations_root.exists():
                expected_metadata.add(self._store.operations_root)
                if any(self._store.operations_root.iterdir()):
                    raise AgentHomeInvariantError(
                        "Empty Home overlay still contains operation entries"
                    )
            if metadata_entries != expected_metadata:
                raise AgentHomeInvariantError(
                    "Empty Home overlay contains unowned metadata"
                )
            for path in self._runtime_root.rglob("*"):
                if (
                    path == self._store.metadata_root
                    or self._store.metadata_root in path.parents
                ):
                    continue
                if path.is_symlink() or not path.is_dir():
                    raise AgentHomeInvariantError(
                        "Empty Home overlay contains unowned runtime content"
                    )
        except AgentHomeInvariantError:
            raise
        except OSError as exc:
            raise AgentHomeIOError(
                f"Failed to validate empty runtime Home: {exc}"
            ) from exc

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
                raise AgentHomeContractError("Home patch max_chars must be positive")
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
                raise AgentHomeIOError(
                    f"Failed to read Home patch target: {exc}"
                ) from exc
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
                    if (
                        source.is_file()
                        and _file_digest(source) == record.baseline_digest
                    ):
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
            if _same_record_content(recorded, operation.after) and self._disk_matches(
                target, operation.after
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
                raise AgentHomeIOError(
                    f"Failed to delete runtime Home file: {exc}"
                ) from exc
            return
        staged = directory / "after"
        if staged.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.replace(staged, target)
            except OSError as exc:
                raise AgentHomeIOError(
                    f"Failed to apply Home operation: {exc}"
                ) from exc
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
            return (
                ""
                if record.state is HomeOverlayState.DELETED
                else record.runtime_digest
            )
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
            if not self._runtime_root.exists():
                return self.initialize()
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
        else HomeOverlayState.MODIFIED if baseline_digest else HomeOverlayState.CREATED
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
        raise AgentHomeInvariantError(
            f"Home runtime path is not a regular file: {path}"
        )
    try:
        stat = path.stat()
    except OSError as exc:
        raise AgentHomeIOError(f"Failed to stat runtime Home file: {exc}") from exc
    digest = _file_digest(path)
    state = (
        HomeOverlayState.COPIED
        if baseline_digest and digest == baseline_digest
        else HomeOverlayState.MODIFIED if baseline_digest else HomeOverlayState.CREATED
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
