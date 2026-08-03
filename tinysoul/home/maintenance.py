"""Stateless review and apply service for the active Agent Home overlay."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
from threading import RLock

from tinysoul.infra.filesystem import (
    TextPrefixRead,
    atomic_write_bytes,
    file_digest,
    read_text_prefix,
)
from tinysoul.infra.json import JsonObject

from .errors import (
    AgentHomeContractError,
    AgentHomeIOError,
    AgentHomeInvariantError,
)
from .layout import AgentHomeLayout
from .overlay import HomeOverlayManager, HomeOverlayRecord, HomeOverlayState


class HomeMaintenanceResolution(StrEnum):
    """Atomic disposition for one token-bound Home change."""

    ACCEPT = "accept"
    REJECT = "reject"
    REWRITE = "rewrite"


@dataclass(frozen=True)
class HomeSkillMemoryContext:
    """Bounded runtime-only memory attached to changes for one general HOW skill."""

    skill: str
    link: str
    digest: str
    text: str
    truncated: bool

    def __post_init__(self) -> None:
        if not self.skill or not self.link or not self.digest:
            raise AgentHomeContractError(
                "Home skill memory identity fields must be non-empty"
            )
        if not isinstance(self.text, str) or not isinstance(self.truncated, bool):
            raise AgentHomeContractError("Home skill memory preview is invalid")

    def to_json(self) -> JsonObject:
        return {
            "skill": self.skill,
            "link": self.link,
            "digest": self.digest,
            "text": self.text,
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class HomeMaintenanceChange:
    """Bounded three-way review facts for one active overlay difference."""

    link: str
    relative_path: str
    state: HomeOverlayState
    baseline_digest: str
    runtime_digest: str
    runtime_size: int
    runtime_mtime_ns: int
    runtime_text: str
    runtime_truncated: bool
    actual_exists: bool
    actual_digest: str
    actual_text: str
    actual_truncated: bool
    skill_memory: HomeSkillMemoryContext | None = None

    def __post_init__(self) -> None:
        if not self.link or not self.relative_path:
            raise AgentHomeContractError(
                "Home maintenance change identity must be non-empty"
            )
        if self.state not in {
            HomeOverlayState.CREATED,
            HomeOverlayState.MODIFIED,
            HomeOverlayState.DELETED,
        }:
            raise AgentHomeContractError(
                "Home maintenance change must be created, modified, or deleted"
            )
        if (
            isinstance(self.runtime_size, bool)
            or not isinstance(self.runtime_size, int)
            or self.runtime_size < 0
            or isinstance(self.runtime_mtime_ns, bool)
            or not isinstance(self.runtime_mtime_ns, int)
            or self.runtime_mtime_ns < 0
        ):
            raise AgentHomeContractError(
                "Home maintenance runtime metadata must be non-negative integers"
            )
        if not isinstance(self.actual_exists, bool) or any(
            not isinstance(value, bool)
            for value in (
                self.runtime_truncated,
                self.actual_truncated,
            )
        ):
            raise AgentHomeContractError("Home maintenance preview flags are invalid")
        if self.actual_exists != bool(self.actual_digest):
            raise AgentHomeContractError(
                "Home maintenance actual identity is inconsistent"
            )
        if self.state is HomeOverlayState.DELETED and self.runtime_digest:
            raise AgentHomeContractError(
                "Deleted Home maintenance change cannot have runtime content"
            )
        if self.state is not HomeOverlayState.DELETED and not self.runtime_digest:
            raise AgentHomeContractError(
                "Non-deleted Home maintenance change requires runtime content"
            )
        if self.skill_memory is not None and not isinstance(
            self.skill_memory,
            HomeSkillMemoryContext,
        ):
            raise AgentHomeContractError(
                "Home maintenance skill_memory context is invalid"
            )

    @property
    def actual_changed_from_baseline(self) -> bool:
        return self.actual_digest != self.baseline_digest

    @property
    def token(self) -> str:
        value = {
            "relative_path": self.relative_path,
            "state": self.state.value,
            "baseline_digest": self.baseline_digest,
            "runtime_digest": self.runtime_digest,
            "runtime_size": self.runtime_size,
            "runtime_mtime_ns": self.runtime_mtime_ns,
            "actual_digest": self.actual_digest,
        }
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "home_change_v1_" + sha256(encoded).hexdigest()

    def to_review_json(self) -> JsonObject:
        value: JsonObject = {
            "token": self.token,
            "link": self.link,
            "relative_path": self.relative_path,
            "state": self.state.value,
            "baseline_digest": self.baseline_digest,
            "runtime": {
                "digest": self.runtime_digest,
                "size": self.runtime_size,
                "text": self.runtime_text,
                "truncated": self.runtime_truncated,
            },
            "actual": {
                "exists": self.actual_exists,
                "digest": self.actual_digest,
                "text": self.actual_text,
                "truncated": self.actual_truncated,
                "changed_from_baseline": self.actual_changed_from_baseline,
            },
        }
        if self.skill_memory is not None:
            value["skill_memory"] = self.skill_memory.to_json()
        return value


@dataclass(frozen=True)
class HomeMaintenancePending:
    """Non-persisted startup eligibility for active Home maintenance work."""

    change_count: int = 0
    skill_memory_count: int = 0

    def __post_init__(self) -> None:
        for value in (self.change_count, self.skill_memory_count):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise AgentHomeContractError(
                    "Home maintenance pending counts must be non-negative integers"
                )

    @property
    def pending(self) -> bool:
        return self.change_count > 0 or self.skill_memory_count > 0


@dataclass(frozen=True)
class HomeMaintenanceSnapshot:
    """Current bounded Home changes after deterministic reconciliation."""

    changes: tuple[HomeMaintenanceChange, ...] = field(default_factory=tuple)
    copied_cleaned: int = 0
    consistent_cleaned: int = 0
    skill_memories_cleared: int = 0

    def __post_init__(self) -> None:
        if any(not isinstance(change, HomeMaintenanceChange) for change in self.changes):
            raise AgentHomeContractError("Home maintenance snapshot changes are invalid")
        for value in (
            self.copied_cleaned,
            self.consistent_cleaned,
            self.skill_memories_cleared,
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise AgentHomeContractError(
                    "Home maintenance snapshot counts must be non-negative integers"
                )
        object.__setattr__(self, "changes", tuple(self.changes))

    @property
    def pending(self) -> bool:
        return bool(self.changes)


@dataclass(frozen=True)
class HomeMaintenanceResolveOutcome:
    link: str
    relative_path: str
    resolution: HomeMaintenanceResolution
    remaining_changes: int

    def __post_init__(self) -> None:
        if not self.link or not self.relative_path:
            raise AgentHomeContractError(
                "Home maintenance resolve outcome identity must be non-empty"
            )
        if not isinstance(self.resolution, HomeMaintenanceResolution):
            raise AgentHomeContractError(
                "Home maintenance resolve outcome resolution is invalid"
            )
        if (
            isinstance(self.remaining_changes, bool)
            or not isinstance(self.remaining_changes, int)
            or self.remaining_changes < 0
        ):
            raise AgentHomeContractError(
                "Home maintenance remaining_changes must be non-negative"
            )


class HomeMaintenanceService:
    """Snapshot and atomically resolve active Home differences."""

    def __init__(
        self,
        *,
        layout: AgentHomeLayout,
        overlay: HomeOverlayManager,
        max_preview_chars: int,
        max_write_chars: int,
    ) -> None:
        if (
            isinstance(max_preview_chars, bool)
            or not isinstance(max_preview_chars, int)
            or max_preview_chars <= 0
            or isinstance(max_write_chars, bool)
            or not isinstance(max_write_chars, int)
            or max_write_chars <= 0
        ):
            raise AgentHomeContractError(
                "Home maintenance limits must be positive integers"
            )
        self._layout = layout
        self._overlay = overlay
        self._max_preview_chars = max_preview_chars
        self._max_write_chars = max_write_chars
        self._lock = RLock()

    def snapshot(self) -> HomeMaintenanceSnapshot:
        """Return current token-bound changes after deterministic cleanup."""

        with self._lock:
            copied_cleaned, consistent_cleaned = self._clean_deterministic_records()
            memories = self._skill_memories()
            changes = tuple(
                self._build_change(record, memories=memories)
                for record in self._reviewable_records()
            )
            pending_by_skill = _pending_changes_by_skill(changes)
            cleared = 0
            for skill in sorted(memories):
                if pending_by_skill.get(skill, 0) == 0:
                    self._clear_skill_memory(skill, memories[skill])
                    cleared += 1
            return HomeMaintenanceSnapshot(
                changes=changes,
                copied_cleaned=copied_cleaned,
                consistent_cleaned=consistent_cleaned,
                skill_memories_cleared=cleared,
            )

    def resolve(
        self,
        token: str,
        resolution: HomeMaintenanceResolution,
        *,
        rewrite_text: str | None = None,
    ) -> HomeMaintenanceResolveOutcome:
        """Atomically resolve the current change identified by ``token``."""

        if not isinstance(token, str) or not token:
            raise AgentHomeContractError(
                "Home maintenance resolve requires a non-empty token"
            )
        if not isinstance(resolution, HomeMaintenanceResolution):
            raise AgentHomeContractError(
                "Home maintenance resolution must be accept, reject, or rewrite"
            )
        if resolution is HomeMaintenanceResolution.REWRITE:
            if not isinstance(rewrite_text, str):
                raise AgentHomeContractError(
                    "Home maintenance rewrite requires text"
                )
            if len(rewrite_text) > self._max_write_chars:
                raise AgentHomeContractError(
                    f"Home maintenance rewrite exceeds {self._max_write_chars} characters"
                )
        elif rewrite_text is not None:
            raise AgentHomeContractError(
                "Only Home maintenance rewrite can carry rewrite_text"
            )

        with self._lock:
            self._clean_deterministic_records()
            memories = self._skill_memories()
            changes = tuple(
                self._build_change(record, memories=memories)
                for record in self._reviewable_records()
            )
            matching = tuple(change for change in changes if change.token == token)
            if len(matching) != 1:
                raise AgentHomeInvariantError(
                    "Home maintenance change token is stale or unknown"
                )
            change = matching[0]
            self._verify_change(change)
            if resolution is HomeMaintenanceResolution.ACCEPT:
                self._apply(change)
            elif resolution is HomeMaintenanceResolution.REWRITE:
                self._rewrite(change, rewrite_text or "")
            self._overlay.clear_record(change.relative_path)
            self._clear_resolved_skill_memory(change, memories=memories)
            remaining = len(self._reviewable_records())
            return HomeMaintenanceResolveOutcome(
                link=change.link,
                relative_path=change.relative_path,
                resolution=resolution,
                remaining_changes=remaining,
            )

    def pending(self) -> HomeMaintenancePending:
        """Report actual review work without cleaning or mutating the overlay."""

        with self._lock:
            changes = len(self._reviewable_records())
            return HomeMaintenancePending(
                change_count=changes,
                skill_memory_count=sum(
                    record.state is not HomeOverlayState.DELETED
                    for record in self._skill_memories().values()
                ),
            )

    def _clean_deterministic_records(self) -> tuple[int, int]:
        copied_cleaned = 0
        consistent_cleaned = 0
        for record in self._overlay.records():
            if _is_skill_memory(record.relative_path):
                continue
            if record.state is HomeOverlayState.COPIED:
                self._clean_copied(record)
                copied_cleaned += 1
            elif self._record_matches_actual(record):
                self._overlay.clear_record(record.relative_path)
                consistent_cleaned += 1
        return copied_cleaned, consistent_cleaned

    def _clean_copied(self, record: HomeOverlayRecord) -> None:
        actual = self._layout.source_for_relative(record.relative_path)
        actual_digest = _actual_digest(actual)
        if actual_digest == record.runtime_digest:
            self._overlay.clear_record(record.relative_path)
            return
        if actual_digest:
            self._overlay.reset_to_actual_copy(record.relative_path)
        else:
            self._overlay.delete(record.relative_path, expected_digest="")
        self._overlay.clear_record(record.relative_path)

    def _record_matches_actual(self, record: HomeOverlayRecord) -> bool:
        actual_digest = _actual_digest(
            self._layout.source_for_relative(record.relative_path)
        )
        if record.state is HomeOverlayState.DELETED:
            return not actual_digest
        return bool(actual_digest) and actual_digest == record.runtime_digest

    def _skill_memories(self) -> dict[str, HomeOverlayRecord]:
        result: dict[str, HomeOverlayRecord] = {}
        for record in self._overlay.records():
            if not _is_skill_memory(record.relative_path):
                continue
            skill = PurePosixPath(record.relative_path).parts[1]
            if record.baseline_digest or record.state is HomeOverlayState.COPIED:
                raise AgentHomeInvariantError(
                    f"Runtime-only SKILL_MEMORY has an actual baseline: {record.relative_path}"
                )
            if skill in result:
                raise AgentHomeInvariantError(
                    f"General HOW skill has multiple SKILL_MEMORY records: {skill}"
                )
            result[skill] = record
        return result

    def _reviewable_records(self) -> tuple[HomeOverlayRecord, ...]:
        return tuple(
            record
            for record in self._overlay.records()
            if not _is_skill_memory(record.relative_path)
            and record.state is not HomeOverlayState.COPIED
            and not self._record_matches_actual(record)
        )

    def _build_change(
        self,
        record: HomeOverlayRecord,
        *,
        memories: dict[str, HomeOverlayRecord],
    ) -> HomeMaintenanceChange:
        if (
            record.state is not HomeOverlayState.DELETED
            and record.size > self._max_write_chars
        ):
            raise AgentHomeInvariantError(
                f"Runtime Home change exceeds write limit: {record.relative_path}"
            )
        link = self._layout.link_for_relative(record.relative_path)
        if link is None:
            raise AgentHomeInvariantError(
                f"Home maintenance cannot map overlay path to a Link: {record.relative_path}"
            )
        actual = self._layout.source_for_relative(record.relative_path)
        actual_digest = _actual_digest(actual)
        actual_read = _preview(actual, self._max_preview_chars) if actual_digest else None
        runtime_read = None
        if record.state is not HomeOverlayState.DELETED:
            runtime = self._layout.runtime_for_relative(record.relative_path)
            runtime_read = _preview(runtime, self._max_preview_chars)
        skill = _skill_for_relative(record.relative_path)
        skill_memory = None
        if skill is not None and skill in memories:
            memory_record = memories[skill]
            if memory_record.state is not HomeOverlayState.DELETED:
                memory_path = self._layout.runtime_for_relative(
                    memory_record.relative_path
                )
                memory_read = _preview(memory_path, self._max_preview_chars)
                skill_memory = HomeSkillMemoryContext(
                    skill=skill,
                    link=f"home:how/{skill}/SKILL_MEMORY.md",
                    digest=memory_record.runtime_digest,
                    text=memory_read.text,
                    truncated=memory_read.truncated,
                )
        return HomeMaintenanceChange(
            link=str(link),
            relative_path=record.relative_path,
            state=record.state,
            baseline_digest=record.baseline_digest,
            runtime_digest=record.runtime_digest,
            runtime_size=record.size,
            runtime_mtime_ns=record.mtime_ns,
            runtime_text=runtime_read.text if runtime_read is not None else "",
            runtime_truncated=(
                runtime_read.truncated if runtime_read is not None else False
            ),
            actual_exists=bool(actual_digest),
            actual_digest=actual_digest,
            actual_text=actual_read.text if actual_read is not None else "",
            actual_truncated=(
                actual_read.truncated if actual_read is not None else False
            ),
            skill_memory=skill_memory,
        )

    def _verify_change(self, change: HomeMaintenanceChange) -> None:
        record = self._overlay.record_for(change.relative_path)
        if record is None or (
            record.state is not change.state
            or record.baseline_digest != change.baseline_digest
            or record.runtime_digest != change.runtime_digest
            or record.size != change.runtime_size
            or record.mtime_ns != change.runtime_mtime_ns
        ):
            raise AgentHomeInvariantError(
                f"Home overlay changed during maintenance: {change.relative_path}"
            )
        actual_digest = _actual_digest(
            self._layout.source_for_relative(change.relative_path)
        )
        if actual_digest != change.actual_digest:
            raise AgentHomeInvariantError(
                f"Actual Home changed during maintenance: {change.relative_path}"
            )

    def _apply(self, change: HomeMaintenanceChange) -> None:
        actual = self._layout.source_for_relative(change.relative_path)
        try:
            if change.state is HomeOverlayState.DELETED:
                actual.unlink(missing_ok=True)
                return
            runtime = self._layout.runtime_for_relative(change.relative_path)
            content = runtime.read_bytes()
            if _digest_bytes(content) != change.runtime_digest:
                raise AgentHomeInvariantError(
                    f"Runtime Home content changed during apply: {change.relative_path}"
                )
            atomic_write_bytes(actual, content)
        except AgentHomeInvariantError:
            raise
        except OSError as exc:
            raise AgentHomeIOError(
                f"Failed to apply Home maintenance change: {exc}"
            ) from exc

    def _rewrite(self, change: HomeMaintenanceChange, text: str) -> None:
        actual = self._layout.source_for_relative(change.relative_path)
        try:
            atomic_write_bytes(actual, text.encode("utf-8"))
        except OSError as exc:
            raise AgentHomeIOError(
                f"Failed to rewrite Home maintenance change: {exc}"
            ) from exc

    def _clear_resolved_skill_memory(
        self,
        change: HomeMaintenanceChange,
        *,
        memories: dict[str, HomeOverlayRecord],
    ) -> None:
        skill = _skill_for_relative(change.relative_path)
        if skill is None or skill not in memories:
            return
        if any(
            _skill_for_relative(record.relative_path) == skill
            for record in self._reviewable_records()
        ):
            return
        self._clear_skill_memory(skill, memories[skill])

    def _clear_skill_memory(
        self,
        skill: str,
        expected: HomeOverlayRecord,
    ) -> None:
        current = self._overlay.record_for(expected.relative_path)
        if current != expected:
            raise AgentHomeInvariantError(
                f"SKILL_MEMORY changed during maintenance: {skill}"
            )
        self._overlay.clear_record(expected.relative_path)

def _actual_digest(path: Path) -> str:
    if not path.exists():
        return ""
    if not path.is_file():
        raise AgentHomeInvariantError(
            f"Actual Home maintenance target is not a regular file: {path}"
        )
    try:
        return file_digest(path)
    except OSError as exc:
        raise AgentHomeIOError(f"Failed to digest actual Home content: {exc}") from exc


def _preview(path: Path, max_chars: int) -> TextPrefixRead:
    try:
        return read_text_prefix(path, max_chars=max_chars)
    except UnicodeDecodeError as exc:
        raise AgentHomeContractError(
            f"Home maintenance content is not UTF-8 text: {path}"
        ) from exc
    except OSError as exc:
        raise AgentHomeIOError(
            f"Failed to read Home maintenance content: {exc}"
        ) from exc


def _is_skill_memory(relative_path: str) -> bool:
    parts = PurePosixPath(relative_path).parts
    return (
        len(parts) == 3
        and parts[0] == "how"
        and parts[2] == "SKILL_MEMORY.md"
    )


def _skill_for_relative(relative_path: str) -> str | None:
    parts = PurePosixPath(relative_path).parts
    if len(parts) >= 3 and parts[0] == "how" and parts[2] != "SKILL_MEMORY.md":
        return parts[1]
    return None


def _pending_changes_by_skill(
    changes: tuple[HomeMaintenanceChange, ...],
) -> dict[str, int]:
    result: dict[str, int] = {}
    for change in changes:
        skill = _skill_for_relative(change.relative_path)
        if skill is not None:
            result[skill] = result.get(skill, 0) + 1
    return result


def _digest_bytes(value: bytes) -> str:
    from hashlib import sha256

    return sha256(value).hexdigest()
