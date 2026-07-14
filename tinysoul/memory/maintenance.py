"""Date-scoped Memory consolidation and atomic persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import re
from threading import RLock
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tinysoul.infra.json import JsonObject, dumps_json
from tinysoul.loop.day import BusinessDay
from tinysoul.runtime import RunScope
from tinysoul.session.memory import SessionMemoryFact, SessionMemoryFactsProjection

from .config import MemoryMaintenanceSettings
from .errors import (
    MemoryContractError,
    MemoryError,
    MemoryInvariantError,
)
from .links import MemoryLink
from .store import MemoryStore


class HomeTopLinkCatalog(Protocol):
    """Read-only actual Home link catalog injected at assembly time."""

    def actual_top_links(self) -> tuple[str, ...]: ...


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
    MEMORY_EXISTS = "memory_exists"


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
            raise MemoryContractError("Memory section bodies must be strings")

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
            raise MemoryContractError("Memory source period is invalid")
        sources = tuple(self.sources)
        if any(not isinstance(source, str) or not source for source in sources):
            raise MemoryContractError(
                "Memory period sources must contain non-empty text"
            )
        object.__setattr__(self, "sources", sources)


@dataclass(frozen=True)
class MemoryConsolidationRequest:
    """Bounded facts and rules for one complete MEMORY replacement."""

    day: BusinessDay
    periods: tuple[MemoryPeriodSources, ...]
    allowed_home_links: tuple[str, ...]
    allowed_memory_links: tuple[str, ...]
    chunk_max_chars: int
    max_calls: int
    validation_retries: int
    max_document_chars: int

    def __post_init__(self) -> None:
        if not isinstance(self.day, BusinessDay):
            raise MemoryContractError(
                "Memory consolidation day must be a BusinessDay"
            )
        periods = tuple(self.periods)
        if tuple(item.period for item in periods) != tuple(MemoryPeriod):
            raise MemoryContractError(
                "Memory consolidation must provide all periods in stable order"
            )
        home_links = tuple(self.allowed_home_links)
        memory_links = tuple(self.allowed_memory_links)
        if len(set(home_links)) != len(home_links):
            raise MemoryContractError(
                "Memory consolidation allowed Home links must be unique"
            )
        if any(not isinstance(link, str) or not link for link in home_links):
            raise MemoryContractError(
                "Memory consolidation allowed Home links must be non-empty text"
            )
        if len(set(memory_links)) != len(memory_links):
            raise MemoryContractError(
                "Memory consolidation allowed Memory links must be unique"
            )
        for link in memory_links:
            if str(MemoryLink.parse(link)) != link:
                raise MemoryContractError(
                    "Memory consolidation allowed Memory link is not canonical"
                )
        for name in ("chunk_max_chars", "max_calls", "max_document_chars"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise MemoryContractError(
                    f"Memory consolidation {name} must be positive"
                )
        if (
            isinstance(self.validation_retries, bool)
            or not isinstance(self.validation_retries, int)
            or self.validation_retries < 0
        ):
            raise MemoryContractError(
                "Memory consolidation validation_retries cannot be negative"
            )
        object.__setattr__(self, "periods", periods)
        object.__setattr__(self, "allowed_home_links", home_links)
        object.__setattr__(self, "allowed_memory_links", memory_links)


@dataclass(frozen=True)
class MemoryConsolidationResult:
    sections: MemorySections
    model_calls: int

    def __post_init__(self) -> None:
        if not isinstance(self.sections, MemorySections):
            raise MemoryContractError(
                "Memory consolidation result sections are invalid"
            )
        if (
            isinstance(self.model_calls, bool)
            or not isinstance(self.model_calls, int)
            or self.model_calls < 0
        ):
            raise MemoryContractError(
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
            raise MemoryContractError("Memory outcome day is invalid")
        if str(MemoryLink.parse(self.link)) != self.link:
            raise MemoryContractError("Memory outcome link is invalid")
        if not isinstance(self.status, MemoryMaintenanceStatus):
            raise MemoryContractError("Memory outcome status is invalid")
        if self.status is MemoryMaintenanceStatus.SKIPPED:
            if not isinstance(self.skip_reason, MemoryMaintenanceSkipReason):
                raise MemoryContractError(
                    "Skipped Memory outcome requires a skip reason"
                )
        elif self.skip_reason is not None:
            raise MemoryContractError(
                "Non-skipped Memory outcome cannot carry a skip reason"
            )
        if self.status is MemoryMaintenanceStatus.FAILED:
            if not isinstance(self.failure, MemoryMaintenanceFailure):
                raise MemoryContractError(
                    "Failed Memory outcome requires a failure kind"
                )
        elif self.failure is not None:
            raise MemoryContractError(
                "Non-failed Memory outcome cannot carry a failure kind"
            )
        for name in ("fact_count", "model_calls"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise MemoryContractError(
                    f"Memory outcome {name} cannot be negative"
                )
        if self.status is MemoryMaintenanceStatus.COMPLETED:
            if not self.document_digest:
                raise MemoryContractError(
                    "Completed Memory outcome requires a document digest"
                )
        elif self.document_digest:
            raise MemoryContractError(
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


class MemoryConsolidationError(MemoryError):
    """A bounded consolidation failure suitable for a run outcome."""

    def __init__(self, failure: MemoryMaintenanceFailure, message: str) -> None:
        super().__init__(message)
        self.failure = failure


class MemoryMaintenanceService:
    """Consolidate one Session projection into one atomic actual MEMORY."""

    def __init__(
        self,
        *,
        store: MemoryStore,
        home_catalog: HomeTopLinkCatalog,
        settings: MemoryMaintenanceSettings,
    ) -> None:
        if not isinstance(settings, MemoryMaintenanceSettings):
            raise MemoryContractError(
                "Memory maintenance settings are invalid"
            )
        if not isinstance(store, MemoryStore):
            raise MemoryContractError("Memory maintenance store is invalid")
        if not hasattr(home_catalog, "actual_top_links"):
            raise MemoryContractError("Memory Home link catalog is invalid")
        self._store = store
        self._home_catalog = home_catalog
        self._settings = settings
        self._lock = RLock()

    def memory_exists(self, day: BusinessDay) -> bool:
        return self._store.exists(_link_for_day(day))

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
        rewrite_existing: bool = True,
        scope: RunScope | None = None,
    ) -> MemoryMaintenanceOutcome:
        with self._lock:
            zone = _business_zone(timezone)
            if projection is None:
                if not isinstance(target_day, BusinessDay):
                    raise MemoryContractError(
                        "Missing Session projection requires target_day"
                    )
                return _skipped(
                    target_day,
                    MemoryMaintenanceSkipReason.SESSION_NOT_FOUND,
                )
            if target_day is not None and target_day != projection.day:
                raise MemoryContractError(
                    "Memory target day must match Session projection day"
                )
            day = projection.day
            if not projection.has_facts:
                return _skipped(day, MemoryMaintenanceSkipReason.SESSION_EMPTY)
            if not isinstance(rewrite_existing, bool):
                raise MemoryContractError(
                    "Memory rewrite_existing must be a boolean"
                )
            if not rewrite_existing and self.memory_exists(day):
                return _skipped(day, MemoryMaintenanceSkipReason.MEMORY_EXISTS)
            if consolidator is None:
                raise MemoryContractError(
                    "Non-empty Memory Maintenance requires a consolidator"
                )
            try:
                old_sections = self._read_existing(day)
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
                allowed_home_links=self._home_catalog.actual_top_links(),
                allowed_memory_links=tuple(
                    str(link)
                    for link in self._store.links()
                    if link != _link_for_day(day)
                ),
                chunk_max_chars=self._settings.chunk_max_chars,
                max_calls=self._settings.max_calls,
                validation_retries=self._settings.validation_retries,
                max_document_chars=self._store.max_document_chars,
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
                    allowed_home_links=frozenset(request.allowed_home_links),
                    allowed_memory_links=frozenset(request.allowed_memory_links),
                    max_document_chars=self._store.max_document_chars,
                )
            except MemoryConsolidationError as exc:
                return _failed(
                    day,
                    exc.failure,
                    fact_count=len(projection.facts),
                )
            saved = self._store.write(_link_for_day(day), document)
            return MemoryMaintenanceOutcome(
                day=day,
                link=str(saved.link),
                status=MemoryMaintenanceStatus.COMPLETED,
                fact_count=len(projection.facts),
                model_calls=result.model_calls,
                document_digest=saved.digest,
            )

    def _read_existing(self, day: BusinessDay) -> MemorySections:
        link = _link_for_day(day)
        if not self._store.exists(link):
            return MemorySections()
        document = self._store.read(link)
        if len(document.text) > self._settings.source_max_chars:
            raise MemoryConsolidationError(
                MemoryMaintenanceFailure.INPUT_TOO_LARGE,
                "Existing MEMORY exceeds the total source limit",
            )
        return parse_memory_document(day, document.text)

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

_HOME_AUTOLINK = re.compile(r"<(home:[^<>\r\n]+)>")
_MEMORY_AUTOLINK = re.compile(r"<(memory:[^<>\r\n]+)>")
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
        raise MemoryInvariantError(
            f"Existing MEMORY has an invalid date or morning heading: {day}"
        )
    morning, separator, remaining = normalized[len(prefix) :].partition(
        afternoon_marker
    )
    if not separator:
        raise MemoryInvariantError(
            f"Existing MEMORY is missing the afternoon heading: {day}"
        )
    afternoon, separator, evening = remaining.partition(evening_marker)
    if not separator:
        raise MemoryInvariantError(
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
    allowed_home_links: frozenset[str],
    allowed_memory_links: frozenset[str],
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
        remaining = _MEMORY_AUTOLINK.sub("", _HOME_AUTOLINK.sub("", body))
        if "home:" in remaining:
            errors.append(
                f"{period.value} contains a Home link outside <home:space@name>"
            )
        for match in _HOME_AUTOLINK.finditer(body):
            value = match.group(1)
            if value not in allowed_home_links:
                errors.append(
                    f"{period.value} references a missing actual Home top link: {value}"
                )
        if "memory:" in remaining:
            errors.append(
                f"{period.value} contains a Memory link outside <memory:YYYY-MM-DD>"
            )
        for match in _MEMORY_AUTOLINK.finditer(body):
            value = match.group(1)
            try:
                parsed = MemoryLink.parse(value)
            except MemoryContractError:
                errors.append(f"{period.value} contains an invalid Memory link")
                continue
            if parsed.day == day.value:
                errors.append(f"{period.value} contains a self Memory link: {value}")
            elif str(parsed) not in allowed_memory_links:
                errors.append(
                    f"{period.value} references a missing Memory: {value}"
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
        raise MemoryInvariantError(
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
        raise MemoryContractError(
            "Memory Maintenance timezone must be a non-empty IANA name"
        )
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise MemoryContractError(
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
        link=str(_link_for_day(day)),
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
        link=str(_link_for_day(day)),
        status=MemoryMaintenanceStatus.FAILED,
        failure=failure,
        fact_count=fact_count,
    )


def _link_for_day(day: BusinessDay) -> MemoryLink:
    if not isinstance(day, BusinessDay):
        raise MemoryContractError("Memory day must be a BusinessDay")
    return MemoryLink(day.value)
