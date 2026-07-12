"""Atomic daily Session persistence."""

from __future__ import annotations

from dataclasses import replace
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
from .models import SessionHistoryKind, SessionManifest, SessionRecord


class SessionStore:
    def __init__(self, *, root: Path) -> None:
        self._root = root
        self._manifest_path = root / "manifest.json"

    @property
    def root(self) -> Path:
        return self._root

    def load_active_manifest(self) -> SessionManifest | None:
        if not self._manifest_path.exists():
            return None
        return self.load_manifest()

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
        """Persist an immutable record or reuse semantically identical content."""

        path = self._record_path(record.ref, kind=record.kind)
        if path.exists():
            existing = self._load_record_path(path, ref=record.ref, kind=record.kind)
            if not _record_contents_match(existing, record):
                raise SessionInvariantError(
                    f"Session record content conflicts with existing ref: {record.ref}"
                )
            return existing
        self._write_object(path, record.to_json(), label="record")
        return record

    def load_record(self, ref: str) -> SessionRecord:
        kind = _ref_kind(ref)
        path = self._record_path(ref, kind=kind)
        if not path.is_file():
            raise SessionContractError(f"Unknown Session history ref: {ref}")
        return self._load_record_path(path, ref=ref, kind=kind)

    def list_records(self, kind: SessionHistoryKind) -> tuple[SessionRecord, ...]:
        directory = self._root / (
            "turns" if kind is SessionHistoryKind.TURN else "summaries"
        )
        if not directory.exists():
            return ()
        if not directory.is_dir():
            raise SessionInvariantError(
                f"Session record location is not a directory: {directory}"
            )
        records: list[SessionRecord] = []
        for path in sorted(directory.glob("*.json"), key=lambda item: item.name):
            record_id = path.stem
            ref = f"session:{kind.value}/{record_id}"
            records.append(self._load_record_path(path, ref=ref, kind=kind))
        return tuple(records)

    def _load_record_path(
        self,
        path: Path,
        *,
        ref: str,
        kind: SessionHistoryKind,
    ) -> SessionRecord:
        try:
            record = SessionRecord.from_json(
                self._read_object(path, label="record")
            )
        except SessionContractError as exc:
            raise SessionInvariantError(
                f"Persisted Session record is invalid: {ref}: {exc}"
            ) from exc
        if record.ref != ref or record.kind is not kind:
            raise SessionInvariantError(f"Session record identity mismatch: {ref}")
        if record.recorded_at_ns == 0:
            try:
                record = replace(record, recorded_at_ns=path.stat().st_mtime_ns)
            except OSError as exc:
                raise SessionIOError(
                    f"Failed to stat legacy Session record: {exc}"
                ) from exc
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

    def archive_to(self, target: Path) -> None:
        if target.exists():
            raise SessionIOError(f"Session archive already exists: {target}")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(self._root, target)
        except OSError as exc:
            raise SessionIOError(f"Failed to archive Session: {exc}") from exc

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


def _ref_kind(ref: str) -> SessionHistoryKind:
    for kind in SessionHistoryKind:
        if ref.startswith(f"session:{kind.value}/"):
            return kind
    raise SessionContractError(f"Invalid Session history ref: {ref}")


def _record_contents_match(left: SessionRecord, right: SessionRecord) -> bool:
    if left.kind is not right.kind or not _record_days_match(left, right):
        return False
    if left.kind is SessionHistoryKind.TURN:
        return all(
            left.content.get(key) == right.content.get(key)
            for key in ("completion", "output", "exhausted")
        )
    if left.kind is SessionHistoryKind.SUMMARY:
        return left.content.get("child_refs") == right.content.get("child_refs")
    return left.content == right.content


def _record_days_match(left: SessionRecord, right: SessionRecord) -> bool:
    left_day = left.content.get("day")
    right_day = right.content.get("day")
    return left_day is None or right_day is None or left_day == right_day
