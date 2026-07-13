"""Stateless review and apply service for the active Agent Home overlay."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath
from threading import RLock
from typing import Protocol

from tinysoul.infra.filesystem import (
    TextPrefixRead,
    atomic_write_bytes,
    file_digest,
    read_text_prefix,
)
from tinysoul.infra.json import JsonObject
from tinysoul.llm import (
    AnswerFormat,
    CallSettings,
    JsonAnswer,
    MessageStack,
    SystemMessage,
    TaskCall,
    TaskProfile,
    TaskResult,
    TaskResultStatus,
    ToolUse,
    UserMessage,
)
from tinysoul.runtime import RunScope

from .errors import (
    AgentHomeContractError,
    AgentHomeIOError,
    AgentHomeInvariantError,
    AgentHomeReviewError,
)
from .layout import AgentHomeLayout
from .overlay import HomeOverlayManager, HomeOverlayRecord, HomeOverlayState


class HomeMaintenanceMode(StrEnum):
    """Decision source used for one Home Maintenance run."""

    AUTOMATIC = "automatic"
    MANUAL = "manual"


class HomeMaintenanceDecision(StrEnum):
    """Allowed disposition for one active Home difference."""

    APPLY = "apply"
    DISCARD = "discard"


class HomeMaintenanceStatus(StrEnum):
    """Completion status for one in-memory Maintenance run."""

    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


class HomeMaintenanceFailure(StrEnum):
    """Stable local failure kinds for a Maintenance run."""

    REVIEW_FAILED = "review_failed"


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

    def to_review_json(self) -> JsonObject:
        value: JsonObject = {
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
class HomeMaintenanceItemOutcome:
    """Decision summary retained only in the current run outcome."""

    link: str
    relative_path: str
    decision: HomeMaintenanceDecision

    def __post_init__(self) -> None:
        if not self.link or not self.relative_path:
            raise AgentHomeContractError(
                "Home maintenance item outcome identity must be non-empty"
            )
        if not isinstance(self.decision, HomeMaintenanceDecision):
            raise AgentHomeContractError(
                "Home maintenance item outcome decision is invalid"
            )


@dataclass(frozen=True)
class HomeMaintenanceOutcome:
    """Bounded, non-persisted result of one Home Maintenance run."""

    status: HomeMaintenanceStatus
    failure: HomeMaintenanceFailure | None = None
    items: tuple[HomeMaintenanceItemOutcome, ...] = field(default_factory=tuple)
    copied_cleaned: int = 0
    consistent_cleaned: int = 0
    skill_memories_cleared: int = 0
    remaining_changes: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.status, HomeMaintenanceStatus):
            raise AgentHomeContractError("Home maintenance outcome status is invalid")
        if self.status is HomeMaintenanceStatus.FAILED:
            if not isinstance(self.failure, HomeMaintenanceFailure):
                raise AgentHomeContractError(
                    "Failed Home maintenance outcome requires a failure kind"
                )
        elif self.failure is not None:
            raise AgentHomeContractError(
                "Non-failed Home maintenance outcome cannot carry a failure kind"
            )
        if any(not isinstance(item, HomeMaintenanceItemOutcome) for item in self.items):
            raise AgentHomeContractError("Home maintenance outcome items are invalid")
        for value in (
            self.copied_cleaned,
            self.consistent_cleaned,
            self.skill_memories_cleared,
            self.remaining_changes,
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise AgentHomeContractError(
                    "Home maintenance outcome counts must be non-negative integers"
                )
        object.__setattr__(self, "items", tuple(self.items))

    @property
    def applied(self) -> int:
        return sum(
            item.decision is HomeMaintenanceDecision.APPLY
            for item in self.items
        )

    @property
    def discarded(self) -> int:
        return sum(
            item.decision is HomeMaintenanceDecision.DISCARD
            for item in self.items
        )


class HomeMaintenanceReviewer(Protocol):
    """Automatic decision boundary for one bounded Home change."""

    def review(
        self,
        change: HomeMaintenanceChange,
        *,
        scope: RunScope,
    ) -> HomeMaintenanceDecision:
        ...


class HomeMaintenanceDecisionProvider(Protocol):
    """Manual decision boundary; None stops before processing the item."""

    def decide(
        self,
        change: HomeMaintenanceChange,
    ) -> HomeMaintenanceDecision | None:
        ...


class HomeMaintenanceModelRunner(Protocol):
    def run(self, call: TaskCall) -> TaskResult:
        ...


class LLMHomeMaintenanceReviewer:
    """Review one Home change through the dedicated JSON-only LLM profile."""

    def __init__(self, runner: HomeMaintenanceModelRunner) -> None:
        self._runner = runner

    def review(
        self,
        change: HomeMaintenanceChange,
        *,
        scope: RunScope,
    ) -> HomeMaintenanceDecision:
        result = self._runner.run(
            TaskCall(
                profile=TaskProfile.HOME_MAINTENANCE,
                messages=MessageStack.of(
                    SystemMessage.from_text(
                        "Review one Agent Home runtime change against current actual "
                        "Home. Apply only when the runtime version should become the "
                        "long-term Home fact; otherwise discard it.",
                        label="home_maintenance_role",
                    ),
                    UserMessage.from_json(
                        change.to_review_json(),
                        label="home_maintenance_change",
                    ),
                    UserMessage.from_text(
                        'Return exactly one JSON object: {"decision":"apply"} '
                        'or {"decision":"discard"}.',
                        label="home_maintenance_output",
                    ),
                ),
                settings=CallSettings(
                    answer_format=AnswerFormat.JSON_OBJECT,
                    tool_use=ToolUse.DISABLED,
                ),
                scope=scope,
            )
        )
        if result.status is TaskResultStatus.FAILURE:
            raise AgentHomeReviewError(
                "Home maintenance reviewer output did not satisfy its protocol"
            )
        if not isinstance(result.answer, JsonAnswer):
            raise AgentHomeReviewError(
                "Home maintenance reviewer did not return a JSON object"
            )
        value = result.answer.value
        if set(value) != {"decision"}:
            raise AgentHomeReviewError(
                "Home maintenance reviewer returned unexpected fields"
            )
        decision = value.get("decision")
        try:
            return HomeMaintenanceDecision(decision)
        except (TypeError, ValueError) as exc:
            raise AgentHomeReviewError(
                "Home maintenance reviewer returned an invalid decision"
            ) from exc


class HomeMaintenanceService:
    """Recompute, decide, apply, and clear active Home differences."""

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

    def run(
        self,
        *,
        mode: HomeMaintenanceMode,
        automatic_reviewer: HomeMaintenanceReviewer | None = None,
        manual_decisions: HomeMaintenanceDecisionProvider | None = None,
        scope: RunScope | None = None,
    ) -> HomeMaintenanceOutcome:
        with self._lock:
            self._validate_decision_boundary(
                mode,
                automatic_reviewer=automatic_reviewer,
                manual_decisions=manual_decisions,
            )
            run_scope = scope or RunScope()
            copied_cleaned, consistent_cleaned = self._clean_deterministic_records()
            memories = self._skill_memories()
            changes = tuple(
                self._build_change(record, memories=memories)
                for record in self._reviewable_records()
            )
            pending_by_skill = _pending_changes_by_skill(changes)
            cleared_skills: set[str] = set()
            cleared_memories = 0
            for skill in sorted(memories):
                if pending_by_skill.get(skill, 0) == 0:
                    self._clear_skill_memory(skill, memories[skill])
                    cleared_skills.add(skill)
                    cleared_memories += 1

            item_outcomes: list[HomeMaintenanceItemOutcome] = []
            status = HomeMaintenanceStatus.COMPLETED
            failure = None
            for change in changes:
                try:
                    decision = self._decision_for(
                        change,
                        mode=mode,
                        automatic_reviewer=automatic_reviewer,
                        manual_decisions=manual_decisions,
                        scope=run_scope,
                    )
                except AgentHomeReviewError:
                    status = HomeMaintenanceStatus.FAILED
                    failure = HomeMaintenanceFailure.REVIEW_FAILED
                    break
                if decision is None:
                    status = HomeMaintenanceStatus.STOPPED
                    break
                self._process_change(change, decision)
                item_outcomes.append(
                    HomeMaintenanceItemOutcome(
                        link=change.link,
                        relative_path=change.relative_path,
                        decision=decision,
                    )
                )
                skill = _skill_for_relative(change.relative_path)
                if skill is not None and skill in pending_by_skill:
                    pending_by_skill[skill] -= 1
                    if (
                        pending_by_skill[skill] == 0
                        and skill in memories
                        and skill not in cleared_skills
                    ):
                        self._clear_skill_memory(skill, memories[skill])
                        cleared_skills.add(skill)
                        cleared_memories += 1

            return HomeMaintenanceOutcome(
                status=status,
                failure=failure,
                items=tuple(item_outcomes),
                copied_cleaned=copied_cleaned,
                consistent_cleaned=consistent_cleaned,
                skill_memories_cleared=cleared_memories,
                remaining_changes=len(self._reviewable_records()),
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

    def _decision_for(
        self,
        change: HomeMaintenanceChange,
        *,
        mode: HomeMaintenanceMode,
        automatic_reviewer: HomeMaintenanceReviewer | None,
        manual_decisions: HomeMaintenanceDecisionProvider | None,
        scope: RunScope,
    ) -> HomeMaintenanceDecision | None:
        if mode is HomeMaintenanceMode.AUTOMATIC:
            if automatic_reviewer is None:
                raise AgentHomeInvariantError(
                    "Automatic Home maintenance reviewer disappeared"
                )
            decision = automatic_reviewer.review(change, scope=scope)
        else:
            if manual_decisions is None:
                raise AgentHomeInvariantError(
                    "Manual Home maintenance decision provider disappeared"
                )
            decision = manual_decisions.decide(change)
            if decision is None:
                return None
        if not isinstance(decision, HomeMaintenanceDecision):
            raise AgentHomeContractError(
                "Home maintenance decision provider returned an invalid decision"
            )
        return decision

    def _process_change(
        self,
        change: HomeMaintenanceChange,
        decision: HomeMaintenanceDecision,
    ) -> None:
        self._verify_change(change)
        if decision is HomeMaintenanceDecision.APPLY:
            self._apply(change)
        self._overlay.clear_record(change.relative_path)

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

    @staticmethod
    def _validate_decision_boundary(
        mode: HomeMaintenanceMode,
        *,
        automatic_reviewer: HomeMaintenanceReviewer | None,
        manual_decisions: HomeMaintenanceDecisionProvider | None,
    ) -> None:
        if not isinstance(mode, HomeMaintenanceMode):
            raise AgentHomeContractError(
                "Home maintenance mode must be automatic or manual"
            )
        if mode is HomeMaintenanceMode.AUTOMATIC:
            if automatic_reviewer is None or manual_decisions is not None:
                raise AgentHomeContractError(
                    "Automatic Home maintenance requires only an automatic reviewer"
                )
        elif manual_decisions is None or automatic_reviewer is not None:
            raise AgentHomeContractError(
                "Manual Home maintenance requires only a decision provider"
            )


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
