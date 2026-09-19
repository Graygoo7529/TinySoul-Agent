"""Persistent effective overlay for the mutable Agent Home working copy."""

from __future__ import annotations

import json
from pathlib import Path

from tinysoul.infra.filesystem import atomic_write_text
from tinysoul.infra.json import JsonObject, to_json_object
from ..errors import AgentHomeIOError, AgentHomeInvariantError


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
