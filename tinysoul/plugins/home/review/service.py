"""Stateless review and apply service for the active Agent Home overlay."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path, PurePosixPath
from threading import RLock

from tinysoul.infra.filesystem import (
    TextPrefixRead,
    atomic_write_bytes,
    file_digest,
    read_text_prefix,
)

from ..errors import (
    AgentHomeContractError,
    AgentHomeIOError,
    AgentHomeInvariantError,
)
from ..content.layout import AgentHomeLayout
from ..links import HomeTopLink
from ..skills.metadata import parse_home_skill_metadata
from ..overlay import HomeOverlayManager, HomeOverlayRecord, HomeOverlayState


from .models import (
    HomeReviewResolution,
    HomeSkillMemoryContext,
    HomeReviewChange,
    HomeSkillReview,
    HomeReviewPending,
    HomeReviewSnapshot,
    HomeReviewResolveOutcome,
)


class HomeReviewService:
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
            raise AgentHomeContractError("Home review limits must be positive integers")
        self._layout = layout
        self._overlay = overlay
        self._max_preview_chars = max_preview_chars
        self._max_write_chars = max_write_chars
        self._lock = RLock()

    def snapshot(self) -> HomeReviewSnapshot:
        """Return current token-bound reviews after deterministic cleanup."""

        with self._lock:
            (
                copied_cleaned,
                consistent_cleaned,
                skill_memories_cleared,
            ) = self._clean_deterministic_records()
            memories = self._skill_memories()
            changes = tuple(
                self._build_change(record) for record in self._reviewable_records()
            )
            skill_reviews = tuple(
                self._build_skill_review(skill, memories[skill])
                for skill in sorted(memories)
            )
            return HomeReviewSnapshot(
                changes=changes,
                skill_reviews=skill_reviews,
                copied_cleaned=copied_cleaned,
                consistent_cleaned=consistent_cleaned,
                skill_memories_cleared=skill_memories_cleared,
            )

    def resolve(
        self,
        token: str,
        resolution: HomeReviewResolution,
        *,
        rewrite_text: str | None = None,
    ) -> HomeReviewResolveOutcome:
        """Atomically resolve the current review identified by ``token``."""

        if not isinstance(token, str) or not token:
            raise AgentHomeContractError(
                "Home review resolve requires a non-empty token"
            )
        if not isinstance(resolution, HomeReviewResolution):
            raise AgentHomeContractError(
                "Home review resolution must be accept, reject, or rewrite"
            )
        if resolution is HomeReviewResolution.REWRITE:
            if not isinstance(rewrite_text, str):
                raise AgentHomeContractError("Home review rewrite requires text")
            if len(rewrite_text) > self._max_write_chars:
                raise AgentHomeContractError(
                    f"Home review rewrite exceeds {self._max_write_chars} characters"
                )
        elif rewrite_text is not None:
            raise AgentHomeContractError(
                "Only Home review rewrite can carry rewrite_text"
            )

        with self._lock:
            self._clean_deterministic_records()
            memories = self._skill_memories()
            changes = tuple(
                self._build_change(record) for record in self._reviewable_records()
            )
            skill_reviews = tuple(
                self._build_skill_review(skill, memories[skill])
                for skill in sorted(memories)
            )
            matching = tuple(
                review for review in (*changes, *skill_reviews) if review.token == token
            )
            if len(matching) != 1:
                raise AgentHomeInvariantError(
                    "Home review review token is stale or unknown"
                )
            review = matching[0]
            if isinstance(review, HomeReviewChange):
                self._resolve_change(review, resolution, rewrite_text=rewrite_text)
            else:
                self._resolve_skill_review(
                    review,
                    resolution,
                    rewrite_text=rewrite_text,
                    expected_memory=memories[review.skill],
                )
            remaining = len(self._reviewable_records()) + sum(
                record.state is not HomeOverlayState.DELETED
                for record in self._skill_memories().values()
            )
            return HomeReviewResolveOutcome(
                link=review.link,
                relative_path=review.relative_path,
                resolution=resolution,
                remaining_reviews=remaining,
            )

    def pending(self) -> HomeReviewPending:
        """Report actual review work without cleaning or mutating the overlay."""

        with self._lock:
            changes = len(self._reviewable_records())
            return HomeReviewPending(
                change_count=changes,
                skill_memory_count=sum(
                    record.state is not HomeOverlayState.DELETED
                    for record in self._skill_memories().values()
                ),
            )

    def _clean_deterministic_records(self) -> tuple[int, int, int]:
        copied_cleaned = 0
        consistent_cleaned = 0
        skill_memories_cleared = 0
        for record in self._overlay.records():
            if _is_skill_memory(record.relative_path):
                if record.state is HomeOverlayState.DELETED:
                    self._overlay.clear_record(record.relative_path)
                    skill_memories_cleared += 1
                continue
            if record.state is HomeOverlayState.COPIED:
                self._clean_copied(record)
                copied_cleaned += 1
            elif self._record_matches_actual(record):
                self._overlay.clear_record(record.relative_path)
                consistent_cleaned += 1
        return copied_cleaned, consistent_cleaned, skill_memories_cleared

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
                    f"General skill has multiple SKILL_MEMORY records: {skill}"
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
    ) -> HomeReviewChange:
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
                f"Home review cannot map overlay path to a Link: {record.relative_path}"
            )
        actual = self._layout.source_for_relative(record.relative_path)
        actual_digest = _actual_digest(actual)
        actual_read = (
            _preview(actual, self._max_preview_chars) if actual_digest else None
        )
        runtime_read = None
        if record.state is not HomeOverlayState.DELETED:
            runtime = self._layout.runtime_for_relative(record.relative_path)
            runtime_read = _preview(runtime, self._max_preview_chars)
        return HomeReviewChange(
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
        )

    def _build_skill_review(
        self,
        skill: str,
        memory_record: HomeOverlayRecord,
    ) -> HomeSkillReview:
        if memory_record.state is HomeOverlayState.DELETED:
            raise AgentHomeInvariantError(
                f"Deleted SKILL_MEMORY remained reviewable: {skill}"
            )
        relative_path = f"skills/{skill}/SKILL.md"
        link = self._layout.link_for_relative(relative_path)
        if link is None:
            raise AgentHomeInvariantError(
                f"Home review cannot map skill review target: {relative_path}"
            )
        actual = self._layout.source_for_relative(relative_path)
        actual_digest = _actual_digest(actual)
        if not actual_digest:
            raise AgentHomeInvariantError(
                f"SKILL_MEMORY has no actual skill review target: {skill}"
            )
        actual_read = _preview(actual, self._max_preview_chars)
        memory_read = _preview(
            self._layout.runtime_for_relative(memory_record.relative_path),
            self._max_preview_chars,
        )
        return HomeSkillReview(
            skill=skill,
            link=str(link),
            relative_path=relative_path,
            actual_digest=actual_digest,
            actual_text=actual_read.text,
            actual_truncated=actual_read.truncated,
            skill_memory=HomeSkillMemoryContext(
                skill=skill,
                link=f"home:skills/{skill}/SKILL_MEMORY.md",
                digest=memory_record.runtime_digest,
                text=memory_read.text,
                truncated=memory_read.truncated,
            ),
        )

    def _resolve_change(
        self,
        change: HomeReviewChange,
        resolution: HomeReviewResolution,
        *,
        rewrite_text: str | None,
    ) -> None:
        self._verify_change(change)
        if resolution is HomeReviewResolution.ACCEPT:
            self._apply(change)
        elif resolution is HomeReviewResolution.REWRITE:
            self._validate_rewrite(change.relative_path, rewrite_text or "")
            self._rewrite_relative(change.relative_path, rewrite_text or "")
        self._overlay.clear_record(change.relative_path)

    def _resolve_skill_review(
        self,
        review: HomeSkillReview,
        resolution: HomeReviewResolution,
        *,
        rewrite_text: str | None,
        expected_memory: HomeOverlayRecord,
    ) -> None:
        if resolution is HomeReviewResolution.ACCEPT:
            raise AgentHomeContractError(
                "Home skill review does not have a runtime version to accept"
            )
        self._verify_skill_review(review, expected_memory=expected_memory)
        if resolution is HomeReviewResolution.REWRITE:
            self._validate_rewrite(review.relative_path, rewrite_text or "")
            self._rewrite_relative(review.relative_path, rewrite_text or "")
        self._clear_skill_memory(review.skill, expected_memory)

    def _validate_rewrite(self, relative_path: str, text: str) -> None:
        """Validate owner-specific rewrite semantics before touching actual Home."""

        link = self._layout.link_for_relative(relative_path)
        if link is None:
            raise AgentHomeInvariantError(
                f"Home review cannot map rewrite target: {relative_path}"
            )
        if (
            isinstance(link, HomeTopLink)
            and link.space == "skills"
            and relative_path == f"skills/{link.name}/SKILL.md"
        ):
            parse_home_skill_metadata(text, link=link)

    def _verify_change(self, change: HomeReviewChange) -> None:
        record = self._overlay.record_for(change.relative_path)
        if record is None or (
            record.state is not change.state
            or record.baseline_digest != change.baseline_digest
            or record.runtime_digest != change.runtime_digest
            or record.size != change.runtime_size
            or record.mtime_ns != change.runtime_mtime_ns
        ):
            raise AgentHomeInvariantError(
                f"Home overlay changed during review: {change.relative_path}"
            )
        actual_digest = _actual_digest(
            self._layout.source_for_relative(change.relative_path)
        )
        if actual_digest != change.actual_digest:
            raise AgentHomeInvariantError(
                f"Actual Home changed during review: {change.relative_path}"
            )

    def _apply(self, change: HomeReviewChange) -> None:
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
                f"Failed to apply Home review change: {exc}"
            ) from exc

    def _verify_skill_review(
        self,
        review: HomeSkillReview,
        *,
        expected_memory: HomeOverlayRecord,
    ) -> None:
        current = self._overlay.record_for(expected_memory.relative_path)
        if current != expected_memory:
            raise AgentHomeInvariantError(
                f"SKILL_MEMORY changed during review: {review.skill}"
            )
        actual_digest = _actual_digest(
            self._layout.source_for_relative(review.relative_path)
        )
        if actual_digest != review.actual_digest:
            raise AgentHomeInvariantError(
                f"Actual skill changed during review: {review.relative_path}"
            )

    def _rewrite_relative(self, relative_path: str, text: str) -> None:
        actual = self._layout.source_for_relative(relative_path)
        try:
            atomic_write_bytes(actual, text.encode("utf-8"))
        except OSError as exc:
            raise AgentHomeIOError(
                f"Failed to rewrite Home review change: {exc}"
            ) from exc

    def _clear_skill_memory(
        self,
        skill: str,
        expected: HomeOverlayRecord,
    ) -> None:
        current = self._overlay.record_for(expected.relative_path)
        if current != expected:
            raise AgentHomeInvariantError(
                f"SKILL_MEMORY changed during review: {skill}"
            )
        self._overlay.clear_record(expected.relative_path)


def _actual_digest(path: Path) -> str:
    if not path.exists():
        return ""
    if not path.is_file():
        raise AgentHomeInvariantError(
            f"Actual Home review target is not a regular file: {path}"
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
            f"Home review content is not UTF-8 text: {path}"
        ) from exc
    except OSError as exc:
        raise AgentHomeIOError(f"Failed to read Home review content: {exc}") from exc


def _is_skill_memory(relative_path: str) -> bool:
    parts = PurePosixPath(relative_path).parts
    return len(parts) == 3 and parts[0] == "skills" and parts[2] == "SKILL_MEMORY.md"


def _digest_bytes(value: bytes) -> str:
    from hashlib import sha256

    return sha256(value).hexdigest()
