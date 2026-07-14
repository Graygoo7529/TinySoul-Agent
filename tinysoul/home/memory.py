"""Date-scoped Memory consolidation and atomic persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
import re
from threading import RLock
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tinysoul.infra.filesystem import atomic_write_text, read_text_prefix
from tinysoul.infra.json import JsonObject, dumps_json
from tinysoul.loop.day import BusinessDay
from tinysoul.runtime import RunScope
from tinysoul.session.memory import SessionMemoryFact, SessionMemoryFactsProjection

from .config import MemoryMaintenanceSettings
from .errors import (
    AgentHomeContractError,
    AgentHomeIOError,
    AgentHomeInvariantError,
    AgentHomeMemoryError,
)
from .layout import AgentHomeLayout
from .links import HomeTopLink


class MemoryPeriod(StrEnum):
    """Fixed local-time sections in one Business Day MEMORY."""

    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"


class MemoryMaintenanceStatus(StrEnum):
    """Result status for one non-persisted Memory Maintenance run."""

    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


class MemoryMaintenanceSkipReason(StrEnum):
    """Stable reasons for a Memory run that intentionally writes nothing."""

    SESSION_NOT_FOUND = "session_not_found"
    SESSION_EMPTY = "session_empty"


class MemoryMaintenanceFailure(StrEnum):
    """Stable local failures that preserve the prior MEMORY file."""

    INPUT_TOO_LARGE = "input_too_large"
    CONSOLIDATION_FAILED = "consolidation_failed"
    INVALID_OUTPUT = "invalid_output"


@dataclass(frozen=True)
class MemorySections:
    """Validated Markdown bodies rendered under fixed period headings."""

    morning: str = ""
    afternoon: str = ""
    evening: str = ""

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str)
            for value in (self.morning, self.afternoon, self.evening)
        ):
            raise AgentHomeContractError("Memory section bodies must be strings")

    def for_period(self, period: MemoryPeriod) -> str:
        if period is MemoryPeriod.MORNING:
            return self.morning
        if period is MemoryPeriod.AFTERNOON:
            return self.afternoon
        return self.evening

    @classmethod
    def from_json(cls, value: JsonObject) -> "MemorySections":
        expected = {period.value for period in MemoryPeriod}
        if set(value) != expected:
            raise MemoryConsolidationError(
                MemoryMaintenanceFailure.INVALID_OUTPUT,
                "Memory output must contain exactly morning, afternoon, and evening",
            )
        return cls(
            morning=_required_text(value, MemoryPeriod.MORNING.value),
            afternoon=_required_text(value, MemoryPeriod.AFTERNOON.value),
            evening=_required_text(value, MemoryPeriod.EVENING.value),
        )


@dataclass(frozen=True)
class MemoryPeriodSources:
    period: MemoryPeriod
    sources: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.period, MemoryPeriod):
            raise AgentHomeContractError("Memory source period is invalid")
        sources = tuple(self.sources)
        if any(not isinstance(source, str) or not source for source in sources):
            raise AgentHomeContractError(
                "Memory period sources must contain non-empty text"
            )
        object.__setattr__(self, "sources", sources)


@dataclass(frozen=True)
class MemoryConsolidationRequest:
    """Bounded facts and rules for one complete MEMORY replacement."""

    day: BusinessDay
    periods: tuple[MemoryPeriodSources, ...]
    allowed_links: tuple[str, ...]
    chunk_max_chars: int
    max_calls: int
    validation_retries: int
    max_document_chars: int

    def __post_init__(self) -> None:
        if not isinstance(self.day, BusinessDay):
            raise AgentHomeContractError(
                "Memory consolidation day must be a BusinessDay"
            )
        periods = tuple(self.periods)
        if tuple(item.period for item in periods) != tuple(MemoryPeriod):
            raise AgentHomeContractError(
                "Memory consolidation must provide all periods in stable order"
            )
        links = tuple(self.allowed_links)
        if len(set(links)) != len(links):
            raise AgentHomeContractError(
                "Memory consolidation allowed links must be unique"
            )
        for link in links:
            if str(HomeTopLink.parse(link)) != link:
                raise AgentHomeContractError(
                    "Memory consolidation allowed link is not canonical"
                )
        for name in ("chunk_max_chars", "max_calls", "max_document_chars"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise AgentHomeContractError(
                    f"Memory consolidation {name} must be positive"
                )
        if (
            isinstance(self.validation_retries, bool)
            or not isinstance(self.validation_retries, int)
            or self.validation_retries < 0
        ):
            raise AgentHomeContractError(
                "Memory consolidation validation_retries cannot be negative"
            )
        object.__setattr__(self, "periods", periods)
        object.__setattr__(self, "allowed_links", links)


@dataclass(frozen=True)
class MemoryConsolidationResult:
    sections: MemorySections
    model_calls: int

    def __post_init__(self) -> None:
        if not isinstance(self.sections, MemorySections):
            raise AgentHomeContractError(
                "Memory consolidation result sections are invalid"
            )
        if (
            isinstance(self.model_calls, bool)
            or not isinstance(self.model_calls, int)
            or self.model_calls < 0
        ):
            raise AgentHomeContractError(
                "Memory consolidation model_calls cannot be negative"
            )


@dataclass(frozen=True)
class MemoryMaintenanceOutcome:
    """Bounded, non-persisted outcome for one Memory Maintenance run."""

    day: BusinessDay
    link: str
    status: MemoryMaintenanceStatus
    skip_reason: MemoryMaintenanceSkipReason | None = None
    failure: MemoryMaintenanceFailure | None = None
    fact_count: int = 0
    model_calls: int = 0
    document_digest: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.day, BusinessDay):
            raise AgentHomeContractError("Memory outcome day is invalid")
        if str(HomeTopLink.parse(self.link)) != self.link:
            raise AgentHomeContractError("Memory outcome link is invalid")
        if not isinstance(self.status, MemoryMaintenanceStatus):
            raise AgentHomeContractError("Memory outcome status is invalid")
        if self.status is MemoryMaintenanceStatus.SKIPPED:
            if not isinstance(self.skip_reason, MemoryMaintenanceSkipReason):
                raise AgentHomeContractError(
                    "Skipped Memory outcome requires a skip reason"
                )
        elif self.skip_reason is not None:
            raise AgentHomeContractError(
                "Non-skipped Memory outcome cannot carry a skip reason"
            )
        if self.status is MemoryMaintenanceStatus.FAILED:
            if not isinstance(self.failure, MemoryMaintenanceFailure):
                raise AgentHomeContractError(
                    "Failed Memory outcome requires a failure kind"
                )
        elif self.failure is not None:
            raise AgentHomeContractError(
                "Non-failed Memory outcome cannot carry a failure kind"
            )
        for name in ("fact_count", "model_calls"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise AgentHomeContractError(
                    f"Memory outcome {name} cannot be negative"
                )
        if self.status is MemoryMaintenanceStatus.COMPLETED:
            if not self.document_digest:
                raise AgentHomeContractError(
                    "Completed Memory outcome requires a document digest"
                )
        elif self.document_digest:
            raise AgentHomeContractError(
                "Incomplete Memory outcome cannot carry a document digest"
            )


class MemoryConsolidator(Protocol):
    def consolidate(
        self,
        request: MemoryConsolidationRequest,
        *,
        scope: RunScope,
    ) -> MemoryConsolidationResult:
        ...


class MemoryConsolidationError(AgentHomeMemoryError):
    """A bounded consolidation failure suitable for a run outcome."""

    def __init__(self, failure: MemoryMaintenanceFailure, message: str) -> None:
        super().__init__(message)
        self.failure = failure


class MemoryMaintenanceService:
    """Consolidate one Session projection into one atomic actual MEMORY."""

    def __init__(
        self,
        *,
        layout: AgentHomeLayout,
        settings: MemoryMaintenanceSettings,
        max_document_chars: int,
    ) -> None:
        if not isinstance(settings, MemoryMaintenanceSettings):
            raise AgentHomeContractError(
                "Memory maintenance settings are invalid"
            )
        if (
            isinstance(max_document_chars, bool)
            or not isinstance(max_document_chars, int)
            or max_document_chars <= 0
        ):
            raise AgentHomeContractError(
                "Memory maintenance document limit must be positive"
            )
        self._layout = layout
        self._settings = settings
        self._max_document_chars = max_document_chars
        self._lock = RLock()

    def memory_exists(self, day: BusinessDay) -> bool:
        path = self._memory_path(day)
        if path.is_symlink():
            raise AgentHomeInvariantError(
                f"Actual Home MEMORY cannot be a symlink: {path}"
            )
        return path.is_file()

    def eligible(self, projection: SessionMemoryFactsProjection | None) -> bool:
        return (
            projection is not None
            and projection.has_facts
            and not self.memory_exists(projection.day)
        )

    def run(
        self,
        *,
        projection: SessionMemoryFactsProjection | None,
        consolidator: MemoryConsolidator | None,
        timezone: str,
        target_day: BusinessDay | None = None,
        scope: RunScope | None = None,
    ) -> MemoryMaintenanceOutcome:
        with self._lock:
            zone = _business_zone(timezone)
            if projection is None:
                if not isinstance(target_day, BusinessDay):
                    raise AgentHomeContractError(
                        "Missing Session projection requires target_day"
                    )
                return _skipped(
                    target_day,
                    MemoryMaintenanceSkipReason.SESSION_NOT_FOUND,
                )
            if target_day is not None and target_day != projection.day:
                raise AgentHomeContractError(
                    "Memory target day must match Session projection day"
                )
            day = projection.day
            if not projection.has_facts:
                return _skipped(day, MemoryMaintenanceSkipReason.SESSION_EMPTY)
            if consolidator is None:
                raise AgentHomeContractError(
                    "Non-empty Memory Maintenance requires a consolidator"
                )
            target = self._memory_path(day)
            try:
                old_sections = self._read_existing(day, target)
                sources = self._sources(
                    projection,
                    zone=zone,
                    old_sections=old_sections,
                )
            except MemoryConsolidationError as exc:
                return _failed(
                    day,
                    exc.failure,
                    fact_count=len(projection.facts),
                )
            request = MemoryConsolidationRequest(
                day=day,
                periods=sources,
                allowed_links=self._actual_top_links(),
                chunk_max_chars=self._settings.chunk_max_chars,
                max_calls=self._settings.max_calls,
                validation_retries=self._settings.validation_retries,
                max_document_chars=self._max_document_chars,
            )
            try:
                result = consolidator.consolidate(
                    request,
                    scope=scope or RunScope(),
                )
                if result.model_calls > self._settings.max_calls:
                    raise MemoryConsolidationError(
                        MemoryMaintenanceFailure.CONSOLIDATION_FAILED,
                        "Memory consolidator exceeded the model call budget",
                    )
                document = _validate_sections(
                    day,
                    result.sections,
                    allowed_links=frozenset(request.allowed_links),
                    max_document_chars=self._max_document_chars,
                )
            except MemoryConsolidationError as exc:
                return _failed(
                    day,
                    exc.failure,
                    fact_count=len(projection.facts),
                )
            try:
                atomic_write_text(target, document)
            except OSError as exc:
                raise AgentHomeIOError(
                    f"Failed to write actual Home MEMORY: {exc}"
                ) from exc
            return MemoryMaintenanceOutcome(
                day=day,
                link=str(HomeTopLink("memory", str(day))),
                status=MemoryMaintenanceStatus.COMPLETED,
                fact_count=len(projection.facts),
                model_calls=result.model_calls,
                document_digest=sha256(document.encode("utf-8")).hexdigest(),
            )

    def _read_existing(self, day: BusinessDay, path: Path) -> MemorySections:
        if not path.exists():
            return MemorySections()
        if path.is_symlink() or not path.is_file():
            raise AgentHomeInvariantError(
                f"Actual Home MEMORY is not a regular file: {path}"
            )
        try:
            read = read_text_prefix(
                path,
                max_chars=self._settings.source_max_chars,
            )
        except UnicodeDecodeError as exc:
            raise AgentHomeInvariantError(
                f"Actual Home MEMORY is not UTF-8 text: {path}"
            ) from exc
        except OSError as exc:
            raise AgentHomeIOError(
                f"Failed to read actual Home MEMORY: {exc}"
            ) from exc
        if read.truncated:
            raise MemoryConsolidationError(
                MemoryMaintenanceFailure.INPUT_TOO_LARGE,
                "Existing MEMORY exceeds the total source limit",
            )
        return parse_memory_document(day, read.text)

    def _sources(
        self,
        projection: SessionMemoryFactsProjection,
        *,
        zone: ZoneInfo,
        old_sections: MemorySections,
    ) -> tuple[MemoryPeriodSources, ...]:
        grouped: dict[MemoryPeriod, list[str]] = {
            period: [] for period in MemoryPeriod
        }
        source_chars = 0

        def append(period: MemoryPeriod, source: str) -> None:
            nonlocal source_chars
            source_chars += len(source)
            if source_chars > self._settings.source_max_chars:
                raise MemoryConsolidationError(
                    MemoryMaintenanceFailure.INPUT_TOO_LARGE,
                    "Memory facts exceed the total source limit",
                )
            grouped[period].append(source)

        for fact in projection.facts:
            period = _period_for(fact, day=projection.day, zone=zone)
            append(
                period,
                dumps_json({"kind": "session_fact", "fact": fact.to_json()})
            )
        for period in MemoryPeriod:
            existing = old_sections.for_period(period).strip()
            if existing:
                append(
                    period,
                    dumps_json(
                        {
                            "kind": "existing_memory",
                            "period": period.value,
                            "markdown": existing,
                        }
                    )
                )
        periods = tuple(
            MemoryPeriodSources(period=period, sources=tuple(grouped[period]))
            for period in MemoryPeriod
        )
        return periods

    def _actual_top_links(self) -> tuple[str, ...]:
        result: dict[str, str] = {}
        for relative in self._layout.actual_top_relatives():
            link = self._layout.top_link_for_relative(relative)
            if link is None:
                continue
            value = str(link)
            previous = result.get(value)
            if previous is not None and previous != relative:
                raise AgentHomeInvariantError(
                    f"Actual Home top link has multiple paths: {value}"
                )
            result[value] = relative
        return tuple(sorted(result))

    def _memory_path(self, day: BusinessDay) -> Path:
        link = HomeTopLink("memory", str(day))
        relative = self._layout.relative_candidates_for_top(link)[0]
        return self._layout.source_for_relative(relative)


_HOME_AUTOLINK = re.compile(r"<(home:[^<>\r\n]+)>")
_PERIOD_LABELS = {
    MemoryPeriod.MORNING: "上午",
    MemoryPeriod.AFTERNOON: "下午",
    MemoryPeriod.EVENING: "晚上",
}


def render_memory_document(day: BusinessDay, sections: MemorySections) -> str:
    return (
        f"# {day}\n\n"
        f"## {_PERIOD_LABELS[MemoryPeriod.MORNING]}\n\n"
        f"{sections.morning.strip()}\n\n"
        f"## {_PERIOD_LABELS[MemoryPeriod.AFTERNOON]}\n\n"
        f"{sections.afternoon.strip()}\n\n"
        f"## {_PERIOD_LABELS[MemoryPeriod.EVENING]}\n\n"
        f"{sections.evening.strip()}\n"
    )


def parse_memory_document(day: BusinessDay, text: str) -> MemorySections:
    normalized = text.replace("\r\n", "\n")
    prefix = f"# {day}\n\n## 上午\n\n"
    afternoon_marker = "\n\n## 下午\n\n"
    evening_marker = "\n\n## 晚上\n\n"
    if not normalized.startswith(prefix):
        raise AgentHomeInvariantError(
            f"Existing MEMORY has an invalid date or morning heading: {day}"
        )
    morning, separator, remaining = normalized[len(prefix) :].partition(
        afternoon_marker
    )
    if not separator:
        raise AgentHomeInvariantError(
            f"Existing MEMORY is missing the afternoon heading: {day}"
        )
    afternoon, separator, evening = remaining.partition(evening_marker)
    if not separator:
        raise AgentHomeInvariantError(
            f"Existing MEMORY is missing the evening heading: {day}"
        )
    return MemorySections(
        morning=morning.strip(),
        afternoon=afternoon.strip(),
        evening=evening.strip(),
    )


def _validate_sections(
    day: BusinessDay,
    sections: MemorySections,
    *,
    allowed_links: frozenset[str],
    max_document_chars: int,
) -> str:
    if not any(
        value.strip()
        for value in (sections.morning, sections.afternoon, sections.evening)
    ):
        raise MemoryConsolidationError(
            MemoryMaintenanceFailure.INVALID_OUTPUT,
            "Memory output cannot discard all non-empty Session facts",
        )
    errors: list[str] = []
    for period in MemoryPeriod:
        body = sections.for_period(period)
        if any(line.startswith("# ") or line.startswith("## ") for line in body.splitlines()):
            errors.append(f"{period.value} contains a framework-owned heading")
        remaining = _HOME_AUTOLINK.sub("", body)
        if "home:" in remaining:
            errors.append(
                f"{period.value} contains a Home link outside <home:space@name>"
            )
        for match in _HOME_AUTOLINK.finditer(body):
            value = match.group(1)
            try:
                parsed = HomeTopLink.parse(value)
            except AgentHomeContractError:
                errors.append(f"{period.value} contains an invalid Home top link")
                continue
            if str(parsed) not in allowed_links:
                errors.append(
                    f"{period.value} references a missing actual Home top link: {value}"
                )
    document = render_memory_document(day, sections)
    if len(document) > max_document_chars:
        errors.append("rendered MEMORY exceeds the document size limit")
    if errors:
        raise MemoryConsolidationError(
            MemoryMaintenanceFailure.INVALID_OUTPUT,
            "; ".join(errors[:8]),
        )
    return document


def _period_for(
    fact: SessionMemoryFact,
    *,
    day: BusinessDay,
    zone: ZoneInfo,
) -> MemoryPeriod:
    local_started_at = fact.started_at.astimezone(zone)
    if local_started_at.date() != day.value:
        raise AgentHomeInvariantError(
            f"Session memory fact starts outside its Business Day: {fact.ref}"
        )
    hour = local_started_at.hour
    if hour < 12:
        return MemoryPeriod.MORNING
    if hour < 18:
        return MemoryPeriod.AFTERNOON
    return MemoryPeriod.EVENING


def _business_zone(value: str) -> ZoneInfo:
    if not isinstance(value, str) or not value:
        raise AgentHomeContractError(
            "Memory Maintenance timezone must be a non-empty IANA name"
        )
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise AgentHomeContractError(
            f"Memory Maintenance timezone is unknown: {value}"
        ) from exc


def _required_text(value: JsonObject, name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str):
        raise MemoryConsolidationError(
            MemoryMaintenanceFailure.INVALID_OUTPUT,
            f"Memory output field must be a string: {name}",
        )
    return item


def _skipped(
    day: BusinessDay,
    reason: MemoryMaintenanceSkipReason,
) -> MemoryMaintenanceOutcome:
    return MemoryMaintenanceOutcome(
        day=day,
        link=str(HomeTopLink("memory", str(day))),
        status=MemoryMaintenanceStatus.SKIPPED,
        skip_reason=reason,
    )


def _failed(
    day: BusinessDay,
    failure: MemoryMaintenanceFailure,
    *,
    fact_count: int,
) -> MemoryMaintenanceOutcome:
    return MemoryMaintenanceOutcome(
        day=day,
        link=str(HomeTopLink("memory", str(day))),
        status=MemoryMaintenanceStatus.FAILED,
        failure=failure,
        fact_count=fact_count,
    )
