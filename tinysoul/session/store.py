"""Atomic persistence for one active Session business day."""

from __future__ import annotations

import json
import os
from pathlib import Path

from tinysoul.infra.filesystem import (
    FilesystemBoundaryError,
    atomic_write_text,
    resolve_under_root,
)
from tinysoul.infra.json import JsonObject, to_json_object

from .errors import SessionContractError, SessionIOError, SessionInvariantError
from .models import (
    SessionManifest,
    SessionRecord,
    SessionRecordKind,
    same_record_facts,
    session_record_from_json,
    session_ref_kind,
)


class SessionStore:
    def __init__(self, *, root: Path) -> None:
        self._root = root
        self._manifest_path = root / "manifest.json"

    @property
    def root(self) -> Path:
        return self._root

    def load_active_manifest(self) -> SessionManifest | None:
        return self.load_manifest() if self._manifest_path.exists() else None

    def create_manifest(self, day: str) -> SessionManifest:
        self._root.mkdir(parents=True, exist_ok=True)
        manifest = SessionManifest(day=day)
        self.save_manifest(manifest)
        return manifest

    def load_manifest(self) -> SessionManifest:
        value = self._read_object(self._manifest_path, label="manifest")
        try:
            return SessionManifest.from_json(value)
        except SessionContractError as exc:
            raise SessionInvariantError(
                f"Persisted Session manifest is invalid: {exc}"
            ) from exc

    def save_manifest(self, manifest: SessionManifest) -> None:
        self._write_object(self._manifest_path, manifest.to_json(), label="manifest")

    def save_record_if_absent(self, record: SessionRecord) -> SessionRecord:
        """Persist one immutable record or reuse identical business facts."""

        path = self._record_path(record.ref, kind=record.kind)
        if path.exists():
            existing = self._load_record_path(path, ref=record.ref, kind=record.kind)
            if not same_record_facts(existing, record):
                raise SessionInvariantError(
                    f"Session record content conflicts with existing ref: {record.ref}"
                )
            return existing
        self._write_object(path, record.to_json(), label="record")
        return record

    def load_record(self, ref: str) -> SessionRecord:
        kind = session_ref_kind(ref)
        path = self._record_path(ref, kind=kind)
        if not path.is_file():
            raise SessionContractError(f"Unknown Session ref: {ref}")
        return self._load_record_path(path, ref=ref, kind=kind)

    def list_records(self, kind: SessionRecordKind) -> tuple[SessionRecord, ...]:
        directory = self._root / _record_directory(kind)
        if not directory.exists():
            return ()
        if not directory.is_dir():
            raise SessionInvariantError(
                f"Session record location is not a directory: {directory}"
            )
        records: list[SessionRecord] = []
        for path in sorted(directory.glob("*.json"), key=lambda item: item.name):
            ref = f"session:{kind.value}/{path.stem}"
            records.append(self._load_record_path(path, ref=ref, kind=kind))
        return tuple(records)

    def archive_to(self, target: Path) -> None:
        if target.exists():
            raise SessionIOError(f"Session archive already exists: {target}")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(self._root, target)
        except OSError as exc:
            raise SessionIOError(f"Failed to archive Session: {exc}") from exc

    def _load_record_path(
        self,
        path: Path,
        *,
        ref: str,
        kind: SessionRecordKind,
    ) -> SessionRecord:
        try:
            record = session_record_from_json(
                self._read_object(path, label="record")
            )
        except SessionContractError as exc:
            raise SessionInvariantError(
                f"Persisted Session record is invalid: {ref}: {exc}"
            ) from exc
        if record.ref != ref or record.kind is not kind:
            raise SessionInvariantError(f"Session record identity mismatch: {ref}")
        return record

    def _record_path(self, ref: str, *, kind: SessionRecordKind) -> Path:
        if session_ref_kind(ref) is not kind:
            raise SessionContractError(f"Invalid Session ref: {ref}")
        record_id = ref.split("/", 1)[1]
        try:
            return resolve_under_root(
                self._root,
                f"{_record_directory(kind)}/{record_id}.json",
            )
        except FilesystemBoundaryError as exc:
            raise SessionContractError(f"Invalid Session ref: {ref}") from exc

    @staticmethod
    def _read_object(path: Path, *, label: str) -> JsonObject:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SessionIOError(f"Failed to read Session {label}: {exc}") from exc
        if not isinstance(raw, dict):
            raise SessionInvariantError(
                f"Persisted Session {label} root must be an object"
            )
        return to_json_object(raw)

    @staticmethod
    def _write_object(path: Path, value: JsonObject, *, label: str) -> None:
        try:
            atomic_write_text(
                path,
                json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            )
        except OSError as exc:
            raise SessionIOError(f"Failed to write Session {label}: {exc}") from exc


def _record_directory(kind: SessionRecordKind) -> str:
    return "turns" if kind is SessionRecordKind.TURN else "summaries"
