"""Durable Maintenance availability projection."""

from __future__ import annotations

import json
from pathlib import Path

from tinysoul.infra.filesystem import atomic_write_text, read_text_prefix
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.infra.time import BusinessDay, BusinessDayError

from .errors import MaintenanceContractError, MaintenanceInvariantError
from .models import MaintenanceAvailability


_SCHEMA_VERSION = 1
_MAX_AVAILABILITY_CHARS = 64 * 1024
_ROOT_FIELDS = {"schema_version", "checked_day", "home", "memory_days"}
_HOME_FIELDS = {"change_count", "skill_memory_count"}


class MaintenanceAvailabilityStore:
    """Persist the single frontend-facing Maintenance prompt sheet."""

    def __init__(self, root: Path) -> None:
        if not isinstance(root, Path):
            raise MaintenanceInvariantError(
                "Maintenance availability root must be a path"
            )
        self._path = root.resolve() / "availability.json"

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> MaintenanceAvailability | None:
        if not self._path.exists():
            return None
        try:
            read = read_text_prefix(
                self._path,
                max_chars=_MAX_AVAILABILITY_CHARS,
            )
            if read.truncated:
                raise MaintenanceInvariantError("Maintenance availability is too large")
            raw = json.loads(read.text)
        except MaintenanceInvariantError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise MaintenanceInvariantError(
                f"Failed to read Maintenance availability: {type(exc).__name__}"
            ) from exc
        if not isinstance(raw, dict):
            raise MaintenanceInvariantError(
                "Maintenance availability root must be an object"
            )
        try:
            return _parse_availability(to_json_object(raw))
        except (BusinessDayError, MaintenanceContractError, TypeError) as exc:
            raise MaintenanceInvariantError(
                f"Persisted Maintenance availability is invalid: {exc}"
            ) from exc

    def require(self) -> MaintenanceAvailability:
        availability = self.load()
        if availability is None:
            raise MaintenanceInvariantError(
                "Maintenance availability has not been initialized"
            )
        return availability

    def save(self, availability: MaintenanceAvailability) -> None:
        value: JsonObject = {
            "schema_version": _SCHEMA_VERSION,
            "checked_day": str(availability.checked_day),
            "home": {
                "change_count": availability.home_change_count,
                "skill_memory_count": availability.home_skill_memory_count,
            },
            "memory_days": [str(day) for day in availability.memory_days],
        }
        try:
            atomic_write_text(
                self._path,
                json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            )
        except OSError as exc:
            raise MaintenanceInvariantError(
                f"Failed to write Maintenance availability: {type(exc).__name__}"
            ) from exc


def _parse_availability(value: JsonObject) -> MaintenanceAvailability:
    if set(value) != _ROOT_FIELDS:
        raise MaintenanceInvariantError("Maintenance availability fields are invalid")
    if value.get("schema_version") != _SCHEMA_VERSION:
        raise MaintenanceInvariantError("Maintenance availability schema is unsupported")
    checked_day = value.get("checked_day")
    if not isinstance(checked_day, str):
        raise MaintenanceInvariantError("Maintenance availability checked_day is invalid")
    home = value.get("home")
    if not isinstance(home, dict) or set(home) != _HOME_FIELDS:
        raise MaintenanceInvariantError("Maintenance availability home state is invalid")
    change_count = _non_negative_int(home.get("change_count"), "change_count")
    skill_count = _non_negative_int(
        home.get("skill_memory_count"),
        "skill_memory_count",
    )
    memory_days = value.get("memory_days")
    if not isinstance(memory_days, list):
        raise MaintenanceInvariantError("Maintenance availability memory_days is invalid")
    parsed_days: list[BusinessDay] = []
    for day in memory_days:
        if not isinstance(day, str):
            raise MaintenanceInvariantError(
                "Maintenance availability memory_days is invalid"
            )
        parsed_days.append(BusinessDay.parse(day))
    return MaintenanceAvailability(
        checked_day=BusinessDay.parse(checked_day),
        home_change_count=change_count,
        home_skill_memory_count=skill_count,
        memory_days=tuple(parsed_days),
    )


def _non_negative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MaintenanceInvariantError(
            f"Maintenance availability {name} must be a non-negative integer"
        )
    return value
