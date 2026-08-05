"""Durable segmented Endpoint observation journal for deep event replay."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from threading import Lock
from typing import TYPE_CHECKING

from tinysoul.infra.filesystem import atomic_write_text
from tinysoul.infra.json import JsonObject, dumps_json, to_json_object
from tinysoul.runtime import ObservationLevel

from .errors import EndpointContractError

if TYPE_CHECKING:
    from .events import EndpointEventEnvelope


_MANIFEST_NAME = "manifest.json"
_PART_PREFIX = "part-"
_PART_SUFFIX = ".ndjson"
_PART_PATTERN = re.compile(r"part-(\d{12})\.ndjson\Z")


@dataclass(frozen=True)
class _PartInfo:
    name: str
    first_sequence: int
    last_sequence: int
    size_bytes: int


@dataclass(frozen=True)
class JournalReadPage:
    """Journal records plus the exact sequence scan boundary."""

    events: tuple[EndpointEventEnvelope, ...]
    scanned_through: int
    complete: bool


class EndpointEventJournal:
    """Append-only NDJSON segment store owned by the Endpoint module.

    Write failures never raise into Observation sinks: the journal marks
    itself degraded and callers continue with the in-memory buffer alone.
    """

    def __init__(
        self,
        root: Path,
        *,
        max_segment_bytes: int = 8 * 1024 * 1024,
        max_total_bytes: int = 256 * 1024 * 1024,
    ) -> None:
        if max_segment_bytes <= 0 or max_total_bytes <= 0:
            raise EndpointContractError("Endpoint journal bounds must be positive")
        if max_segment_bytes > max_total_bytes:
            raise EndpointContractError(
                "Endpoint journal segment size cannot exceed total budget"
            )
        self._root = root
        self._max_segment_bytes = max_segment_bytes
        self._max_total_bytes = max_total_bytes
        self._lock = Lock()
        self._degraded = False
        self._failure: JsonObject | None = None
        self._latest_sequence = 0
        self._parts: list[_PartInfo] = []
        self._current_path: Path | None = None
        self._current_bytes = 0
        self._open()

    @property
    def latest_sequence(self) -> int:
        with self._lock:
            return self._latest_sequence

    @property
    def degraded(self) -> bool:
        with self._lock:
            return self._degraded

    @property
    def oldest_sequence(self) -> int | None:
        with self._lock:
            if not self._parts:
                return None
            return self._parts[0].first_sequence

    @property
    def failure(self) -> JsonObject | None:
        with self._lock:
            return self._failure

    def append(self, envelope: EndpointEventEnvelope) -> None:
        """Best-effort append; failures degrade the journal without raising."""

        with self._lock:
            if self._degraded:
                return
            try:
                self._append_locked(envelope)
            except Exception as exc:
                self._mark_degraded_locked("append", exc)

    def read_after(
        self,
        *,
        after: int,
        mode: ObservationLevel,
        limit: int,
    ) -> tuple[EndpointEventEnvelope, ...]:
        return self.read_after_page(after=after, mode=mode, limit=limit).events

    def read_after_page(
        self,
        *,
        after: int,
        mode: ObservationLevel,
        limit: int,
    ) -> JournalReadPage:
        from .events import _level_rank

        if after < 0 or limit <= 0:
            raise EndpointContractError("Endpoint journal read bounds are invalid")
        with self._lock:
            if self._degraded or not self._parts:
                return JournalReadPage((), after, True)
            selected: list[EndpointEventEnvelope] = []
            scanned_through = after
            try:
                for part in self._parts:
                    if part.last_sequence <= after:
                        scanned_through = max(scanned_through, part.last_sequence)
                        continue
                    for envelope in self._read_part(part):
                        scanned_through = max(scanned_through, envelope.sequence)
                        if envelope.sequence <= after:
                            continue
                        if _level_rank(envelope.level) > _level_rank(mode):
                            continue
                        selected.append(envelope)
                        if len(selected) >= limit:
                            return JournalReadPage(
                                tuple(selected), scanned_through, False
                            )
                return JournalReadPage(tuple(selected), scanned_through, True)
            except Exception as exc:
                self._mark_degraded_locked("read", exc)
                return JournalReadPage(tuple(selected), scanned_through, False)

    def _open(self) -> None:
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            self._reconcile_parts()
            self._trim_locked()
            self._persist_manifest()
        except Exception as exc:
            self._mark_degraded_locked("open", exc)

    def _reconcile_parts(self) -> None:
        """Rebuild the manifest from owned segment files.

        The manifest is an index cache. A partial final line is recoverable;
        corruption in any closed segment is treated as a durable gap.
        """

        paths = sorted(
            (
                path
                for path in self._root.iterdir()
                if path.is_file() and _PART_PATTERN.fullmatch(path.name)
            ),
            key=lambda path: path.name,
        )
        parts: list[_PartInfo] = []
        previous: int | None = None
        for index, path in enumerate(paths):
            data = path.read_bytes()
            if data and not data.endswith(b"\n"):
                if index != len(paths) - 1:
                    raise EndpointContractError(
                        f"journal segment has a partial non-tail record: {path.name}"
                    )
                data = data[: data.rfind(b"\n") + 1]
                path.write_bytes(data)
            records: list[EndpointEventEnvelope] = []
            for line in data.splitlines():
                if not line.strip():
                    continue
                raw = json.loads(line.decode("utf-8"))
                if not isinstance(raw, dict):
                    raise EndpointContractError("journal event record is invalid")
                records.append(_envelope_from_json(to_json_object(raw)))
            if not records:
                path.unlink(missing_ok=True)
                continue
            for envelope in records:
                if previous is not None and envelope.sequence != previous + 1:
                    raise EndpointContractError("journal sequence is not contiguous")
                previous = envelope.sequence
            parts.append(
                _PartInfo(
                    name=path.name,
                    first_sequence=records[0].sequence,
                    last_sequence=records[-1].sequence,
                    size_bytes=path.stat().st_size,
                )
            )
        self._parts = parts
        self._latest_sequence = previous or 0
        self._current_path = self._root / parts[-1].name if parts else None
        self._current_bytes = parts[-1].size_bytes if parts else 0

    def _append_locked(self, envelope: EndpointEventEnvelope) -> None:
        if envelope.sequence != self._latest_sequence + 1:
            raise EndpointContractError(
                "journal append sequence must be contiguous"
            )
        line = dumps_json(envelope.to_json()).encode("utf-8") + b"\n"
        if len(line) > self._max_segment_bytes:
            raise EndpointContractError(
                "journal event exceeds the segment byte budget"
            )
        if (
            self._current_path is None
            or self._current_bytes + len(line) > self._max_segment_bytes
        ):
            self._rotate_locked(envelope.sequence)
        assert self._current_path is not None
        with self._current_path.open("ab") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        self._current_bytes += len(line)
        self._latest_sequence = envelope.sequence
        last = self._parts[-1]
        self._parts[-1] = _PartInfo(
            name=last.name,
            first_sequence=last.first_sequence,
            last_sequence=envelope.sequence,
            size_bytes=self._current_bytes,
        )
        self._trim_locked()
        self._persist_manifest()

    def _rotate_locked(self, first_sequence: int) -> None:
        name = f"{_PART_PREFIX}{first_sequence:012d}{_PART_SUFFIX}"
        path = self._root / name
        if path.exists():
            if path.stat().st_size > 0:
                raise EndpointContractError(f"journal segment already exists: {name}")
            path.unlink()
        path.touch(exist_ok=False)
        self._parts.append(
            _PartInfo(
                name=name,
                first_sequence=first_sequence,
                last_sequence=first_sequence - 1,
                size_bytes=0,
            )
        )
        self._current_path = path
        self._current_bytes = 0

    def _trim_locked(self) -> None:
        total = sum(part.size_bytes for part in self._parts)
        while len(self._parts) > 1 and total > self._max_total_bytes:
            removed = self._parts.pop(0)
            path = self._root / removed.name
            if path.exists():
                path.unlink()
            total -= removed.size_bytes

    def _persist_manifest(self) -> None:
        payload: JsonObject = {
            "latest_sequence": self._latest_sequence,
            "parts": [
                {
                    "name": part.name,
                    "first_sequence": part.first_sequence,
                    "last_sequence": part.last_sequence,
                    "size_bytes": part.size_bytes,
                }
                for part in self._parts
            ],
        }
        atomic_write_text(self._root / _MANIFEST_NAME, dumps_json(payload))

    def _mark_degraded_locked(
        self,
        operation: str,
        error: BaseException | None,
    ) -> None:
        self._degraded = True
        self._current_path = None
        self._failure = {
            "operation": operation,
            "kind": "storage",
            "error_type": type(error).__name__ if error is not None else "UnknownError",
        }

    def _read_part(self, part: _PartInfo) -> list[EndpointEventEnvelope]:
        from .events import EndpointEventEnvelope

        path = self._root / part.name
        events: list[EndpointEventEnvelope] = []
        expected = part.first_sequence
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                raw = json.loads(text)
                if not isinstance(raw, dict):
                    raise EndpointContractError("journal event record is invalid")
                envelope = _envelope_from_json(to_json_object(raw))
                if envelope.sequence != expected:
                    raise EndpointContractError("journal sequence is not contiguous")
                events.append(envelope)
                expected += 1
        return events


def _envelope_from_json(raw: JsonObject) -> EndpointEventEnvelope:
    from .events import EndpointEventEnvelope

    sequence = raw.get("sequence")
    name = raw.get("name")
    level_value = raw.get("level")
    source = raw.get("source")
    message = raw.get("message")
    created_at = raw.get("created_at")
    scope_raw = raw.get("scope", [])
    payload = raw.get("payload", {})
    if (
        isinstance(sequence, bool)
        or not isinstance(sequence, int)
        or sequence <= 0
        or not isinstance(name, str)
        or not isinstance(level_value, str)
        or not isinstance(source, str)
        or not isinstance(message, str)
        or isinstance(created_at, bool)
        or not isinstance(created_at, (int, float))
        or not isinstance(scope_raw, list)
        or not isinstance(payload, dict)
    ):
        raise EndpointContractError("journal event record is invalid")
    scope: list[JsonObject] = []
    for item in scope_raw:
        if not isinstance(item, dict):
            raise EndpointContractError("journal event scope is invalid")
        scope.append(to_json_object(item))
    encoded = dumps_json(raw).encode("utf-8")
    return EndpointEventEnvelope(
        sequence=sequence,
        name=name,
        level=ObservationLevel(level_value),
        source=source,
        scope=tuple(scope),
        message=message,
        payload=to_json_object(payload),
        created_at=float(created_at),
        size_bytes=len(encoded),
    )
