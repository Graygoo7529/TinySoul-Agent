"""Archive date index; the day coordinator owns serialization."""

from __future__ import annotations
import json
from pathlib import Path
from tinysoul.infra.filesystem import read_text_prefix, atomic_write_text
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.infra.time import CalendarDay, CalendarDayError
from .errors import ArchiveInvariantError

_CATALOG_SCHEMA_VERSION = 1
_CATALOG_FIELDS = {"schema_version", "entries"}
_CATALOG_ENTRY_FIELDS = {"day", "archive_name"}
_MAX_CATALOG_CHARS = 4 * 1024 * 1024


class ArchiveCatalog:
    def __init__(self, archive_root: Path) -> None:
        self._archive_root = archive_root

    def load(self) -> dict[CalendarDay, str]:
        path = self._archive_root / "catalog.json"
        if not path.exists():
            return {}
        try:
            read = read_text_prefix(path, max_chars=_MAX_CATALOG_CHARS)
        except (OSError, UnicodeError) as exc:
            raise ArchiveInvariantError(
                f"Failed to read Daily archive catalog: {type(exc).__name__}"
            ) from exc
        if read.truncated:
            raise ArchiveInvariantError("Daily archive catalog is too large")
        try:
            raw = json.loads(read.text)
            value = to_json_object(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ArchiveInvariantError(
                "Daily archive catalog is not valid JSON"
            ) from exc
        if set(value) != _CATALOG_FIELDS:
            raise ArchiveInvariantError("Daily archive catalog fields are invalid")
        if value.get("schema_version") != _CATALOG_SCHEMA_VERSION:
            raise ArchiveInvariantError("Daily archive catalog schema is unsupported")
        entries = value.get("entries")
        if not isinstance(entries, list):
            raise ArchiveInvariantError("Daily archive catalog entries are invalid")
        result: dict[CalendarDay, str] = {}
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != _CATALOG_ENTRY_FIELDS:
                raise ArchiveInvariantError("Daily archive catalog entry is invalid")
            day_value = entry.get("day")
            archive_name = entry.get("archive_name")
            if not isinstance(day_value, str):
                raise ArchiveInvariantError(
                    "Daily archive catalog entry day is invalid"
                )
            if (
                not isinstance(archive_name, str)
                or not archive_name
                or Path(archive_name).name != archive_name
                or archive_name.startswith(".")
            ):
                raise ArchiveInvariantError(
                    "Daily archive catalog entry archive_name is invalid"
                )
            try:
                day = CalendarDay.parse(day_value)
            except (CalendarDayError, TypeError) as exc:
                raise ArchiveInvariantError(
                    "Daily archive catalog entry day is invalid"
                ) from exc
            if day in result:
                raise ArchiveInvariantError(
                    f"Multiple archives claim one Business Day: {day}"
                )
            result[day] = archive_name
        return result

    def record(
        self,
        day: CalendarDay,
        archive_name: str,
    ) -> None:
        entries = self.load()
        previous = entries.get(day)
        if previous is not None and previous != archive_name:
            raise ArchiveInvariantError(
                f"Multiple archives claim one Business Day: {day}"
            )
        entries[day] = archive_name
        value: JsonObject = {
            "schema_version": _CATALOG_SCHEMA_VERSION,
            "entries": [
                {"day": str(item_day), "archive_name": entries[item_day]}
                for item_day in sorted(entries)
            ],
        }
        try:
            atomic_write_text(
                self._archive_root / "catalog.json",
                json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            )
        except OSError as exc:
            raise ArchiveInvariantError(
                f"Failed to write Daily archive catalog: {type(exc).__name__}"
            ) from exc
