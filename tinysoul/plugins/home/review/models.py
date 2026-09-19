"""Stateless review and apply service for the active Agent Home overlay."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
import json

from tinysoul.infra.json import JsonObject

from ..errors import AgentHomeContractError
from ..overlay import HomeOverlayState


class HomeReviewResolution(StrEnum):
    """Atomic disposition for one token-bound Home change."""

    ACCEPT = "accept"
    REJECT = "reject"
    REWRITE = "rewrite"


@dataclass(frozen=True)
class HomeSkillMemoryContext:
    """Bounded runtime-only reference for one general skill review."""

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
class HomeReviewChange:
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

    def __post_init__(self) -> None:
        if not self.link or not self.relative_path:
            raise AgentHomeContractError(
                "Home review change identity must be non-empty"
            )
        if self.state not in {
            HomeOverlayState.CREATED,
            HomeOverlayState.MODIFIED,
            HomeOverlayState.DELETED,
        }:
            raise AgentHomeContractError(
                "Home review change must be created, modified, or deleted"
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
                "Home review runtime metadata must be non-negative integers"
            )
        if not isinstance(self.actual_exists, bool) or any(
            not isinstance(value, bool)
            for value in (
                self.runtime_truncated,
                self.actual_truncated,
            )
        ):
            raise AgentHomeContractError("Home review preview flags are invalid")
        if self.actual_exists != bool(self.actual_digest):
            raise AgentHomeContractError("Home review actual identity is inconsistent")
        if self.state is HomeOverlayState.DELETED and self.runtime_digest:
            raise AgentHomeContractError(
                "Deleted Home review change cannot have runtime content"
            )
        if self.state is not HomeOverlayState.DELETED and not self.runtime_digest:
            raise AgentHomeContractError(
                "Non-deleted Home review change requires runtime content"
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
            "kind": "change",
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
            "allowed_resolutions": ["accept", "reject", "rewrite"],
        }
        return value


@dataclass(frozen=True)
class HomeSkillReview:
    """Token-bound review of an actual skill using runtime-only skill memory."""

    skill: str
    link: str
    relative_path: str
    actual_digest: str
    actual_text: str
    actual_truncated: bool
    skill_memory: HomeSkillMemoryContext

    def __post_init__(self) -> None:
        if not self.skill or not self.link or not self.relative_path:
            raise AgentHomeContractError(
                "Home skill review identity fields must be non-empty"
            )
        if not self.actual_digest:
            raise AgentHomeContractError("Home skill review requires actual content")
        if not isinstance(self.actual_text, str) or not isinstance(
            self.actual_truncated,
            bool,
        ):
            raise AgentHomeContractError("Home skill review preview is invalid")
        if not isinstance(self.skill_memory, HomeSkillMemoryContext):
            raise AgentHomeContractError("Home skill review memory is invalid")

    @property
    def token(self) -> str:
        value = {
            "relative_path": self.relative_path,
            "actual_digest": self.actual_digest,
            "skill_memory_digest": self.skill_memory.digest,
        }
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "home_skill_review_v1_" + sha256(encoded).hexdigest()

    def to_review_json(self) -> JsonObject:
        return {
            "kind": "skill_review",
            "token": self.token,
            "skill": self.skill,
            "link": self.link,
            "relative_path": self.relative_path,
            "actual": {
                "digest": self.actual_digest,
                "text": self.actual_text,
                "truncated": self.actual_truncated,
            },
            "skill_memory": self.skill_memory.to_json(),
            "allowed_resolutions": ["reject", "rewrite"],
        }


HomeReview = HomeReviewChange | HomeSkillReview


@dataclass(frozen=True)
class HomeReviewPending:
    """Non-persisted startup eligibility for active Home review work."""

    change_count: int = 0
    skill_memory_count: int = 0

    def __post_init__(self) -> None:
        for value in (self.change_count, self.skill_memory_count):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise AgentHomeContractError(
                    "Home review pending counts must be non-negative integers"
                )

    @property
    def pending(self) -> bool:
        return self.change_count > 0 or self.skill_memory_count > 0


@dataclass(frozen=True)
class HomeReviewSnapshot:
    """Current bounded Home reviews after deterministic reconciliation."""

    changes: tuple[HomeReviewChange, ...] = field(default_factory=tuple)
    skill_reviews: tuple[HomeSkillReview, ...] = field(default_factory=tuple)
    copied_cleaned: int = 0
    consistent_cleaned: int = 0
    skill_memories_cleared: int = 0

    def __post_init__(self) -> None:
        if any(not isinstance(change, HomeReviewChange) for change in self.changes):
            raise AgentHomeContractError("Home review snapshot changes are invalid")
        if any(
            not isinstance(review, HomeSkillReview) for review in self.skill_reviews
        ):
            raise AgentHomeContractError(
                "Home review snapshot skill reviews are invalid"
            )
        for value in (
            self.copied_cleaned,
            self.consistent_cleaned,
            self.skill_memories_cleared,
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise AgentHomeContractError(
                    "Home review snapshot counts must be non-negative integers"
                )
        object.__setattr__(self, "changes", tuple(self.changes))
        object.__setattr__(self, "skill_reviews", tuple(self.skill_reviews))

    @property
    def reviews(self) -> tuple[HomeReview, ...]:
        return (*self.changes, *self.skill_reviews)

    @property
    def pending(self) -> bool:
        return bool(self.reviews)


@dataclass(frozen=True)
class HomeReviewResolveOutcome:
    link: str
    relative_path: str
    resolution: HomeReviewResolution
    remaining_reviews: int

    def __post_init__(self) -> None:
        if not self.link or not self.relative_path:
            raise AgentHomeContractError(
                "Home review resolve outcome identity must be non-empty"
            )
        if not isinstance(self.resolution, HomeReviewResolution):
            raise AgentHomeContractError(
                "Home review resolve outcome resolution is invalid"
            )
        if (
            isinstance(self.remaining_reviews, bool)
            or not isinstance(self.remaining_reviews, int)
            or self.remaining_reviews < 0
        ):
            raise AgentHomeContractError(
                "Home review remaining_reviews must be non-negative"
            )
