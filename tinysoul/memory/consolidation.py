"""Date-scoped Memory consolidation and atomic persistence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from threading import RLock
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tinysoul.infra.json import JsonObject, dumps_json
from tinysoul.infra.time import BusinessDay
from tinysoul.runtime import (
    NullObservationEmitter,
    ObservationEmitter,
    ObservationEvent,
    ObservationLevel,
    RunScope,
    emit_observation,
    observation_enabled,
)
from tinysoul.session.memory import SessionMemoryFact, SessionMemoryFactsProjection

from .config import MemoryConsolidationSettings
from .errors import MemoryContractError, MemoryError, MemoryInvariantError
from .links import MemoryLink
from .store import MemoryStore


class HomeTopLinkCatalog(Protocol):
    """Read-only actual Home link catalog injected at assembly time."""

    def actual_top_links(self) -> tuple[str, ...]: ...


class MemoryConsolidationStatus(StrEnum):
    """Result status for one non-persisted Memory consolidation run."""

    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


class MemoryConsolidationSkipReason(StrEnum):
    """Stable reasons for a Memory run that intentionally writes nothing."""

    SESSION_NOT_FOUND = "session_not_found"
    SESSION_EMPTY = "session_empty"
    MEMORY_EXISTS = "memory_exists"


class MemoryConsolidationFailure(StrEnum):
    """Stable local failures that preserve the prior MEMORY file."""

    INPUT_TOO_LARGE = "input_too_large"
    CONSOLIDATION_FAILED = "consolidation_failed"
    INVALID_OUTPUT = "invalid_output"


@dataclass(frozen=True)
class MemoryConsolidationRequest:
    """Bounded sources and local validation rules for one replacement."""

    day: BusinessDay
    sources: tuple[str, ...]
    allowed_home_links: tuple[str, ...]
    allowed_memory_links: tuple[str, ...]
    home_link_hints: tuple[str, ...]
    memory_link_hints: tuple[str, ...]
    link_hints_max_chars: int
    chunk_max_chars: int
    max_calls: int
    validation_retries: int
    max_document_chars: int

    def __post_init__(self) -> None:
        if not isinstance(self.day, BusinessDay):
            raise MemoryContractError(
                "Memory consolidation day must be a BusinessDay"
            )
        sources = tuple(self.sources)
        if not sources or any(
            not isinstance(source, str) or not source for source in sources
        ):
            raise MemoryContractError(
                "Memory consolidation sources must contain non-empty text"
            )
        home_links = _unique_links(
            self.allowed_home_links,
            name="allowed Home",
        )
        memory_links = _unique_links(
            self.allowed_memory_links,
            name="allowed Memory",
            memory=True,
        )
        home_hints = _unique_links(self.home_link_hints, name="Home hint")
        memory_hints = _unique_links(
            self.memory_link_hints,
            name="Memory hint",
            memory=True,
        )
        if not set(home_hints).issubset(home_links):
            raise MemoryContractError(
                "Memory consolidation Home hints must be locally allowed"
            )
        if not set(memory_hints).issubset(memory_links):
            raise MemoryContractError(
                "Memory consolidation Memory hints must be locally allowed"
            )
        for name in (
            "link_hints_max_chars",
            "chunk_max_chars",
            "max_calls",
            "max_document_chars",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise MemoryContractError(
                    f"Memory consolidation {name} must be positive"
                )
        if _link_hints_size(home_hints, memory_hints) > self.link_hints_max_chars:
            raise MemoryContractError(
                "Memory consolidation Link hints exceed their character budget"
            )
        if (
            isinstance(self.validation_retries, bool)
            or not isinstance(self.validation_retries, int)
            or self.validation_retries < 0
        ):
            raise MemoryContractError(
                "Memory consolidation validation_retries cannot be negative"
            )
        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "allowed_home_links", home_links)
        object.__setattr__(self, "allowed_memory_links", memory_links)
        object.__setattr__(self, "home_link_hints", home_hints)
        object.__setattr__(self, "memory_link_hints", memory_hints)


@dataclass(frozen=True)
class MemoryConsolidationResult:
    body: str
    model_calls: int

    def __post_init__(self) -> None:
        if not isinstance(self.body, str):
            raise MemoryContractError("Memory consolidation body must be text")
        if (
            isinstance(self.model_calls, bool)
            or not isinstance(self.model_calls, int)
            or self.model_calls < 0
        ):
            raise MemoryContractError(
                "Memory consolidation model_calls cannot be negative"
            )


@dataclass(frozen=True)
class MemoryConsolidationOutcome:
    """Bounded, non-persisted outcome for one Memory consolidation run."""

    day: BusinessDay
    link: str
    status: MemoryConsolidationStatus
    skip_reason: MemoryConsolidationSkipReason | None = None
    failure: MemoryConsolidationFailure | None = None
    fact_count: int = 0
    model_calls: int = 0
    document_digest: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.day, BusinessDay):
            raise MemoryContractError("Memory outcome day is invalid")
        if str(MemoryLink.parse(self.link)) != self.link:
            raise MemoryContractError("Memory outcome link is invalid")
        if not isinstance(self.status, MemoryConsolidationStatus):
            raise MemoryContractError("Memory outcome status is invalid")
        if self.status is MemoryConsolidationStatus.SKIPPED:
            if not isinstance(self.skip_reason, MemoryConsolidationSkipReason):
                raise MemoryContractError(
                    "Skipped Memory outcome requires a skip reason"
                )
        elif self.skip_reason is not None:
            raise MemoryContractError(
                "Non-skipped Memory outcome cannot carry a skip reason"
            )
        if self.status is MemoryConsolidationStatus.FAILED:
            if not isinstance(self.failure, MemoryConsolidationFailure):
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
        if self.status is MemoryConsolidationStatus.COMPLETED:
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
    ) -> MemoryConsolidationResult: ...


class MemoryConsolidationError(MemoryError):
    """A bounded consolidation failure suitable for a run outcome."""

    def __init__(self, failure: MemoryConsolidationFailure, message: str) -> None:
        super().__init__(message)
        self.failure = failure


class MemoryConsolidationService:
    """Consolidate one Session projection into one atomic actual MEMORY."""

    def __init__(
        self,
        *,
        store: MemoryStore,
        home_catalog: HomeTopLinkCatalog,
        settings: MemoryConsolidationSettings,
        observations: ObservationEmitter | None = None,
    ) -> None:
        if not isinstance(settings, MemoryConsolidationSettings):
            raise MemoryContractError("Memory consolidation settings are invalid")
        if not isinstance(store, MemoryStore):
            raise MemoryContractError("Memory consolidation store is invalid")
        if not hasattr(home_catalog, "actual_top_links"):
            raise MemoryContractError("Memory Home link catalog is invalid")
        self._store = store
        self._home_catalog = home_catalog
        self._settings = settings
        self._observations = observations or NullObservationEmitter()
        self._lock = RLock()

    def memory_exists(self, day: BusinessDay) -> bool:
        return self._store.exists(_link_for_day(day))

    def eligible(self, projection: SessionMemoryFactsProjection | None) -> bool:
        if projection is None or not projection.has_facts:
            return False
        link = _link_for_day(projection.day)
        if not self._store.exists(link):
            return True
        self._store.read(link)
        return False

    def run(
        self,
        *,
        projection: SessionMemoryFactsProjection | None,
        consolidator: MemoryConsolidator | None,
        timezone: str,
        target_day: BusinessDay | None = None,
        rewrite_existing: bool = True,
        scope: RunScope | None = None,
    ) -> MemoryConsolidationOutcome:
        run_scope = scope or RunScope()
        day = projection.day if projection is not None else target_day
        started_payload: JsonObject = {
            "target_day": str(day) if day is not None else "unknown",
            "rewrite_existing": (
                rewrite_existing
                if isinstance(rewrite_existing, bool)
                else "invalid"
            ),
        }
        self._emit(
            "memory.consolidation.started",
            "Memory consolidation started.",
            scope=run_scope,
            payload=started_payload,
        )
        try:
            outcome = self._run(
                projection=projection,
                consolidator=consolidator,
                timezone=timezone,
                target_day=target_day,
                rewrite_existing=rewrite_existing,
                scope=run_scope,
            )
        except Exception as exc:
            self._emit(
                "memory.consolidation.failed",
                "Memory consolidation failed.",
                scope=run_scope,
                payload={
                    **started_payload,
                    "error_type": type(exc).__name__,
                },
            )
            raise
        terminal = {
            MemoryConsolidationStatus.COMPLETED: "completed",
            MemoryConsolidationStatus.SKIPPED: "skipped",
            MemoryConsolidationStatus.FAILED: "failed",
        }[outcome.status]
        payload: JsonObject = {
            "target_day": str(outcome.day),
            "link": outcome.link,
            "fact_count": outcome.fact_count,
            "model_calls": outcome.model_calls,
        }
        if outcome.skip_reason is not None:
            payload["skip_reason"] = outcome.skip_reason.value
        if outcome.failure is not None:
            payload["failure"] = outcome.failure.value
        if outcome.document_digest:
            payload["document_digest"] = outcome.document_digest
        self._emit(
            f"memory.consolidation.{terminal}",
            f"Memory consolidation {terminal}.",
            scope=run_scope,
            payload=payload,
        )
        return outcome

    def _run(
        self,
        *,
        projection: SessionMemoryFactsProjection | None,
        consolidator: MemoryConsolidator | None,
        timezone: str,
        target_day: BusinessDay | None = None,
        rewrite_existing: bool = True,
        scope: RunScope | None = None,
    ) -> MemoryConsolidationOutcome:
        with self._lock:
            zone = _business_zone(timezone)
            if projection is None:
                if not isinstance(target_day, BusinessDay):
                    raise MemoryContractError(
                        "Missing Session projection requires target_day"
                    )
                return _skipped(
                    target_day,
                    MemoryConsolidationSkipReason.SESSION_NOT_FOUND,
                )
            if target_day is not None and target_day != projection.day:
                raise MemoryContractError(
                    "Memory target day must match Session projection day"
                )
            day = projection.day
            if not projection.has_facts:
                return _skipped(day, MemoryConsolidationSkipReason.SESSION_EMPTY)
            if not isinstance(rewrite_existing, bool):
                raise MemoryContractError(
                    "Memory rewrite_existing must be a boolean"
                )
            try:
                existing = self._read_existing(day)
                if not rewrite_existing and existing is not None:
                    return _skipped(
                        day,
                        MemoryConsolidationSkipReason.MEMORY_EXISTS,
                    )
                sources = self._sources(
                    projection,
                    zone=zone,
                    existing=existing,
                )
                allowed_home_links = self._home_catalog.actual_top_links()
                allowed_memory_links = tuple(
                    str(link)
                    for link in self._store.links()
                    if link != _link_for_day(day)
                )
                home_hints, memory_hints = _source_link_hints(
                    sources,
                    allowed_home_links=frozenset(allowed_home_links),
                    allowed_memory_links=frozenset(allowed_memory_links),
                    max_chars=self._settings.link_hints_max_chars,
                )
            except MemoryConsolidationError as exc:
                return _failed(
                    day,
                    exc.failure,
                    fact_count=len(projection.facts),
                )
            if consolidator is None:
                raise MemoryContractError(
                    "Non-empty Memory consolidation requires a consolidator"
                )
            request = MemoryConsolidationRequest(
                day=day,
                sources=sources,
                allowed_home_links=allowed_home_links,
                allowed_memory_links=allowed_memory_links,
                home_link_hints=home_hints,
                memory_link_hints=memory_hints,
                link_hints_max_chars=self._settings.link_hints_max_chars,
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
                        MemoryConsolidationFailure.CONSOLIDATION_FAILED,
                        "Memory consolidator exceeded the model call budget",
                    )
                document = validate_memory_body(
                    day,
                    result.body,
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
            return MemoryConsolidationOutcome(
                day=day,
                link=str(saved.link),
                status=MemoryConsolidationStatus.COMPLETED,
                fact_count=len(projection.facts),
                model_calls=result.model_calls,
                document_digest=saved.digest,
            )

    def _emit(
        self,
        name: str,
        message: str,
        *,
        scope: RunScope,
        payload: JsonObject,
    ) -> None:
        if not observation_enabled(
            self._observations,
            ObservationLevel.VERBOSE,
        ):
            return
        emit_observation(
            self._observations,
            ObservationEvent(
                name=name,
                level=ObservationLevel.VERBOSE,
                source="memory.consolidation",
                scope=scope,
                message=message,
                payload=payload,
            ),
        )

    def _read_existing(self, day: BusinessDay) -> str | None:
        link = _link_for_day(day)
        if not self._store.exists(link):
            return None
        document = self._store.read(link)
        if len(document.text) > self._settings.source_max_chars:
            raise MemoryConsolidationError(
                MemoryConsolidationFailure.INPUT_TOO_LARGE,
                "Existing MEMORY exceeds the total source limit",
            )
        return document.text

    def _sources(
        self,
        projection: SessionMemoryFactsProjection,
        *,
        zone: ZoneInfo,
        existing: str | None,
    ) -> tuple[str, ...]:
        sources: list[str] = []
        source_chars = 0

        def append(source: str) -> None:
            nonlocal source_chars
            source_chars += len(source)
            if source_chars > self._settings.source_max_chars:
                raise MemoryConsolidationError(
                    MemoryConsolidationFailure.INPUT_TOO_LARGE,
                    "Memory sources exceed the total source limit",
                )
            sources.append(source)

        for fact in projection.facts:
            _validate_fact_day(fact, day=projection.day, zone=zone)
            append(dumps_json({"kind": "session_fact", "fact": fact.to_json()}))
        if existing is not None:
            append(
                dumps_json(
                    {
                        "kind": "existing_memory",
                        "markdown": existing,
                    }
                )
            )
        return tuple(sources)


_HOME_AUTOLINK = re.compile(r"<(home:[^<>\r\n]+)>")
_MEMORY_AUTOLINK = re.compile(r"<(memory:[^<>\r\n]+)>")
_ATX_LEVEL_ONE = re.compile(r"^ {0,3}#(?:[ \t]+|$)")
_SETEXT_LEVEL_ONE = re.compile(r"^ {0,3}=+[ \t]*$")


def render_memory_document(day: BusinessDay, body: str) -> str:
    if not isinstance(day, BusinessDay):
        raise MemoryContractError("Memory render day must be a BusinessDay")
    if not isinstance(body, str):
        raise MemoryContractError("Memory render body must be text")
    return f"# {day}\n\n{body.strip()}\n"


def validate_memory_body(
    day: BusinessDay,
    body: str,
    *,
    allowed_home_links: frozenset[str],
    allowed_memory_links: frozenset[str],
    max_document_chars: int,
) -> str:
    if not isinstance(body, str) or not body.strip():
        raise MemoryConsolidationError(
            MemoryConsolidationFailure.INVALID_OUTPUT,
            "Memory output cannot discard all non-empty Session facts",
        )
    errors: list[str] = []
    if _contains_level_one_heading(body):
        errors.append("Memory body contains a framework-owned level-1 heading")
    remaining = _MEMORY_AUTOLINK.sub("", _HOME_AUTOLINK.sub("", body))
    if "home:" in remaining:
        errors.append("Memory body contains a Home link outside <home:space@name>")
    for match in _HOME_AUTOLINK.finditer(body):
        value = match.group(1)
        if value not in allowed_home_links:
            errors.append(
                f"Memory body references a missing actual Home top link: {value}"
            )
    if "memory:" in remaining:
        errors.append(
            "Memory body contains a Memory link outside <memory:YYYY-MM-DD>"
        )
    for match in _MEMORY_AUTOLINK.finditer(body):
        value = match.group(1)
        try:
            parsed = MemoryLink.parse(value)
        except MemoryContractError:
            errors.append("Memory body contains an invalid Memory link")
            continue
        if parsed.day == day.value:
            errors.append(f"Memory body contains a self Memory link: {value}")
        elif str(parsed) not in allowed_memory_links:
            errors.append(f"Memory body references a missing Memory: {value}")
    document = render_memory_document(day, body)
    if len(document) > max_document_chars:
        errors.append("rendered MEMORY exceeds the document size limit")
    if errors:
        raise MemoryConsolidationError(
            MemoryConsolidationFailure.INVALID_OUTPUT,
            "; ".join(errors[:8]),
        )
    return document


def _source_link_hints(
    sources: tuple[str, ...],
    *,
    allowed_home_links: frozenset[str],
    allowed_memory_links: frozenset[str],
    max_chars: int,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    home: list[str] = []
    memory: list[str] = []
    seen: set[str] = set()
    used = 0
    for source in sources:
        matches = [
            *(
                (match.start(), "home", match.group(1))
                for match in _HOME_AUTOLINK.finditer(source)
            ),
            *(
                (match.start(), "memory", match.group(1))
                for match in _MEMORY_AUTOLINK.finditer(source)
            ),
        ]
        for _, owner, value in sorted(matches):
            allowed = (
                allowed_home_links if owner == "home" else allowed_memory_links
            )
            if value in seen or value not in allowed:
                continue
            added = len(value) + (1 if seen else 0)
            if used + added > max_chars:
                continue
            seen.add(value)
            used += added
            (home if owner == "home" else memory).append(value)
    return tuple(home), tuple(memory)


def _contains_level_one_heading(body: str) -> bool:
    lines = body.splitlines()
    for index, line in enumerate(lines):
        if _ATX_LEVEL_ONE.match(line):
            return True
        if (
            index > 0
            and lines[index - 1].strip()
            and _SETEXT_LEVEL_ONE.match(line)
        ):
            return True
    return False


def _validate_fact_day(
    fact: SessionMemoryFact,
    *,
    day: BusinessDay,
    zone: ZoneInfo,
) -> None:
    if fact.started_at.astimezone(zone).date() != day.value:
        raise MemoryInvariantError(
            f"Session memory fact starts outside its Business Day: {fact.ref}"
        )


def _business_zone(value: str) -> ZoneInfo:
    if not isinstance(value, str) or not value:
        raise MemoryContractError(
            "Memory consolidation timezone must be a non-empty IANA name"
        )
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise MemoryContractError(
            f"Memory consolidation timezone is unknown: {value}"
        ) from exc


def _unique_links(
    values: tuple[str, ...],
    *,
    name: str,
    memory: bool = False,
) -> tuple[str, ...]:
    links = tuple(values)
    if len(set(links)) != len(links):
        raise MemoryContractError(
            f"Memory consolidation {name} links must be unique"
        )
    if any(not isinstance(link, str) or not link for link in links):
        raise MemoryContractError(
            f"Memory consolidation {name} links must be non-empty text"
        )
    if memory:
        for link in links:
            if str(MemoryLink.parse(link)) != link:
                raise MemoryContractError(
                    f"Memory consolidation {name} link is not canonical"
                )
    return links


def _link_hints_size(
    home_links: tuple[str, ...],
    memory_links: tuple[str, ...],
) -> int:
    values = (*home_links, *memory_links)
    return sum(len(value) for value in values) + max(0, len(values) - 1)


def _skipped(
    day: BusinessDay,
    reason: MemoryConsolidationSkipReason,
) -> MemoryConsolidationOutcome:
    return MemoryConsolidationOutcome(
        day=day,
        link=str(_link_for_day(day)),
        status=MemoryConsolidationStatus.SKIPPED,
        skip_reason=reason,
    )


def _failed(
    day: BusinessDay,
    failure: MemoryConsolidationFailure,
    *,
    fact_count: int,
) -> MemoryConsolidationOutcome:
    return MemoryConsolidationOutcome(
        day=day,
        link=str(_link_for_day(day)),
        status=MemoryConsolidationStatus.FAILED,
        failure=failure,
        fact_count=fact_count,
    )


def _link_for_day(day: BusinessDay) -> MemoryLink:
    if not isinstance(day, BusinessDay):
        raise MemoryContractError("Memory day must be a BusinessDay")
    return MemoryLink(day.value)
