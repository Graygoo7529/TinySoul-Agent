"""Atomic daily Session persistence."""

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

from .errors import SessionContractError, SessionIOError
from .models import SessionHistoryKind, SessionManifest, SessionRecord


class SessionStore:
    def __init__(self, *, root: Path, archive_root: Path) -> None:
        self._root = root
        self._archive_root = archive_root
        self._manifest_path = root / "manifest.json"

    def initialize(self, day: str) -> SessionManifest:
        if self._manifest_path.exists():
            manifest = self.load_manifest()
            if manifest.day == day:
                return manifest
            self._archive(manifest.day)
        self._root.mkdir(parents=True, exist_ok=True)
        manifest = SessionManifest(day=day)
        self.save_manifest(manifest)
        return manifest

    def load_manifest(self) -> SessionManifest:
        value = self._read_object(self._manifest_path, label="manifest")
        return SessionManifest.from_json(value)

    def save_manifest(self, manifest: SessionManifest) -> None:
        self._write_object(self._manifest_path, manifest.to_json(), label="manifest")

    def save_record(self, record: SessionRecord) -> None:
        path = self._record_path(record.ref, kind=record.kind)
        if path.exists():
            raise SessionContractError(f"Session record already exists: {record.ref}")
        self._write_object(path, record.to_json(), label="record")

    def load_record(self, ref: str) -> SessionRecord:
        kind = _ref_kind(ref)
        path = self._record_path(ref, kind=kind)
        if not path.is_file():
            raise SessionContractError(f"Unknown Session history ref: {ref}")
        record = SessionRecord.from_json(self._read_object(path, label="record"))
        if record.ref != ref or record.kind is not kind:
            raise SessionContractError(f"Session record identity mismatch: {ref}")
        return record

    def _record_path(self, ref: str, *, kind: SessionHistoryKind) -> Path:
        prefix = f"session:{kind.value}/"
        if not ref.startswith(prefix):
            raise SessionContractError(f"Invalid Session history ref: {ref}")
        record_id = ref[len(prefix) :]
        if not record_id or any(
            char not in "abcdefghijklmnopqrstuvwxyz0123456789_-"
            for char in record_id
        ):
            raise SessionContractError(f"Invalid Session history ref: {ref}")
        directory = "turns" if kind is SessionHistoryKind.TURN else "summaries"
        try:
            return resolve_under_root(self._root, f"{directory}/{record_id}.json")
        except FilesystemBoundaryError as exc:
            raise SessionContractError(f"Invalid Session history ref: {ref}") from exc

    def _archive(self, day: str) -> None:
        target = self._archive_root / day
        if target.exists():
            raise SessionIOError(f"Session archive already exists: {target}")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(self._root, target)
        except OSError as exc:
            raise SessionIOError(f"Failed to archive Session day {day}: {exc}") from exc

    @staticmethod
    def _read_object(path: Path, *, label: str) -> JsonObject:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SessionIOError(f"Failed to read Session {label}: {exc}") from exc
        if not isinstance(raw, dict):
            raise SessionContractError(f"Session {label} root must be an object")
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


def _ref_kind(ref: str) -> SessionHistoryKind:
    for kind in SessionHistoryKind:
        if ref.startswith(f"session:{kind.value}/"):
            return kind
    raise SessionContractError(f"Invalid Session history ref: {ref}")
