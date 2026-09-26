"""Typed retrieval sources, candidate operations and bounded result views."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import TypeAlias

from tinysoul.infra.json import JsonObject, to_json_object


class SourceKind(StrEnum):
    QUERY = "query"
    BACKLINKS = "backlinks"
    DIRECTORY = "directory"
    REFS = "refs"
    RESULT = "result"


class OperationKind(StrEnum):
    FILTER = "filter"
    SELECT = "select"
    RERANK = "rerank"


class SearchContext(StrEnum):
    NONE = "none"
    CURRENT = "current"


class QueryChannel(StrEnum):
    LEXICAL = "lexical"
    EMBEDDING = "embedding"


class SearchFailureKind(StrEnum):
    INVALID_REQUEST = "invalid_request"
    SCOPE_REQUIRED = "scope_required"
    SOURCE_UNAVAILABLE = "source_unavailable"
    OPERATION_FAILED = "operation_failed"
    VIEW_EXPIRED = "view_expired"


class SearchFailure(Exception):
    """A finite retrieval failure mapped by an Action or SDK boundary."""

    def __init__(self, kind: SearchFailureKind, message: str, *, step: str = "") -> None:
        super().__init__(message)
        self.kind = kind
        self.step = step


@dataclass(frozen=True)
class TextQuery:
    text: str

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise SearchFailure(SearchFailureKind.INVALID_REQUEST, "Query must not be empty")


@dataclass(frozen=True)
class DocumentQuery:
    document_ref: str

    def __post_init__(self) -> None:
        if not self.document_ref:
            raise SearchFailure(SearchFailureKind.INVALID_REQUEST, "Document query requires an identity")


class ResourceScopeKind(StrEnum):
    WORKSPACE = "workspace"
    DIRECTORY = "directory"
    FILE = "file"


@dataclass(frozen=True)
class ResourceScope:
    kind: ResourceScopeKind
    locator: str

    def __post_init__(self) -> None:
        valid = self.locator == "" if self.kind is ResourceScopeKind.WORKSPACE else self.locator.startswith("workspace:") and self.locator != "workspace:"
        if not valid:
            raise SearchFailure(SearchFailureKind.INVALID_REQUEST, "Invalid resource scope")

    def to_json(self) -> JsonObject:
        return {"kind": self.kind.value, "locator": self.locator}


@dataclass(frozen=True)
class QuerySource:
    scope: str | ResourceScope
    query: TextQuery | DocumentQuery
    where: JsonObject = field(default_factory=dict)
    literal: bool = False
    regex: bool = False
    case_sensitive: bool = False

    def __post_init__(self) -> None:
        if not self.scope:
            raise SearchFailure(SearchFailureKind.INVALID_REQUEST, "Query source requires a scope")
        object.__setattr__(self, "where", to_json_object(self.where))


@dataclass(frozen=True)
class BacklinksSource:
    scope: str | ResourceScope
    anchor_ref: str
    where: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.scope or not self.anchor_ref:
            raise SearchFailure(SearchFailureKind.INVALID_REQUEST, "Backlinks source requires scope and anchor_ref")
        object.__setattr__(self, "where", to_json_object(self.where))


@dataclass(frozen=True)
class DirectorySource:
    scope: str | ResourceScope
    where: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.scope:
            raise SearchFailure(SearchFailureKind.INVALID_REQUEST, "Directory source requires a scope")
        object.__setattr__(self, "where", to_json_object(self.where))


@dataclass(frozen=True)
class RefsSource:
    refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.refs or any(not ref for ref in self.refs):
            raise SearchFailure(SearchFailureKind.INVALID_REQUEST, "Refs source requires non-empty refs")


@dataclass(frozen=True)
class ResultSource:
    result_ref: str

    def __post_init__(self) -> None:
        if not self.result_ref:
            raise SearchFailure(SearchFailureKind.INVALID_REQUEST, "Result source requires result_ref")


SearchSource: TypeAlias = QuerySource | BacklinksSource | DirectorySource | RefsSource | ResultSource


@dataclass(frozen=True)
class FilterStep:
    where: JsonObject
    op: OperationKind = field(default=OperationKind.FILTER, init=False)

    def __post_init__(self) -> None:
        if not self.where:
            raise SearchFailure(SearchFailureKind.INVALID_REQUEST, "Filter requires a non-empty where")
        object.__setattr__(self, "where", to_json_object(self.where))


@dataclass(frozen=True)
class ModelStep:
    op: OperationKind
    criterion: str
    context: SearchContext = SearchContext.NONE

    def __post_init__(self) -> None:
        if self.op not in {OperationKind.SELECT, OperationKind.RERANK} or not self.criterion.strip():
            raise SearchFailure(SearchFailureKind.INVALID_REQUEST, "Select and rerank require a criterion")


SearchStep: TypeAlias = FilterStep | ModelStep


@dataclass(frozen=True)
class RetrievalRequest:
    source: SearchSource
    steps: tuple[SearchStep, ...] = ()
    exclude_refs: tuple[str, ...] = ()
    page_limit: int = 20
    page_max_chars: int | None = None

    def __post_init__(self) -> None:
        if type(self.page_limit) is not int or self.page_limit < 1:
            raise SearchFailure(SearchFailureKind.INVALID_REQUEST, "Page limit must be positive")
        if len(set(self.exclude_refs)) != len(self.exclude_refs) or any(not ref for ref in self.exclude_refs):
            raise SearchFailure(SearchFailureKind.INVALID_REQUEST, "exclude_refs must contain unique non-empty refs")

    @property
    def source_kind(self) -> SourceKind:
        if isinstance(self.source, QuerySource):
            return SourceKind.QUERY
        if isinstance(self.source, BacklinksSource):
            return SourceKind.BACKLINKS
        if isinstance(self.source, DirectorySource):
            return SourceKind.DIRECTORY
        if isinstance(self.source, RefsSource):
            return SourceKind.REFS
        return SourceKind.RESULT


@dataclass(frozen=True)
class ContentUnit:
    id: str
    ref: str
    text: str
    kind: str = "content"
    location: JsonObject = field(default_factory=dict)
    complete: bool = True

    def __post_init__(self) -> None:
        if not self.id or not self.ref or not isinstance(self.text, str):
            raise SearchFailure(SearchFailureKind.INVALID_REQUEST, "ContentUnit requires id, ref and text")
        object.__setattr__(self, "location", to_json_object(self.location))

    def to_json(self) -> JsonObject:
        return {"id": self.id, "ref": self.ref, "text": self.text, "kind": self.kind, "location": self.location, "complete": self.complete}


@dataclass(frozen=True)
class SearchEvidence:
    ref: str
    text: str
    relation: str = "content"
    unit_id: str | None = None
    basis: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.ref or not self.relation:
            raise SearchFailure(SearchFailureKind.INVALID_REQUEST, "Evidence requires a readable identity and relation")

    def to_json(self) -> JsonObject:
        value: JsonObject = {"ref": self.ref, "text": self.text, "relation": self.relation}
        if self.unit_id:
            value["unit_id"] = self.unit_id
        if self.basis:
            value["basis"] = list(self.basis)
        return value


@dataclass(frozen=True)
class SearchCandidate:
    ref: str
    title: str
    evidence: tuple[SearchEvidence, ...]
    attributes: JsonObject = field(default_factory=dict)
    score_kind: str | None = None
    score: float | None = None
    reason: str | None = None
    evidence_complete: bool = True
    content_units: tuple[ContentUnit, ...] = ()
    basis: tuple[str, ...] = ()
    evaluation: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.ref or not self.evidence:
            raise SearchFailure(SearchFailureKind.INVALID_REQUEST, "Candidate requires identity and source evidence")
        object.__setattr__(self, "attributes", to_json_object(self.attributes))
        if not self.content_units:
            object.__setattr__(
                self,
                "content_units",
                tuple(ContentUnit(item.unit_id or f"{item.ref}:unit{index}", item.ref, item.text, item.relation, complete=self.evidence_complete) for index, item in enumerate(self.evidence)),
            )

        object.__setattr__(self, "evidence", tuple(
            replace(item, unit_id=item.unit_id or f"{item.ref}:unit{index}")
            for index, item in enumerate(self.evidence)
        ))

    @property
    def text(self) -> str:
        return self.title + "\n" + "\n".join(item.text for item in self.evidence)

    def to_json(self, *, rank: int) -> JsonObject:
        value: JsonObject = {"ref": self.ref, "title": self.title, "rank": rank, "evidence": [item.to_json() for item in self.evidence], "content_coverage": "full" if self.evidence_complete else "excerpt", "attributes": self.attributes}
        if self.evaluation:
            value["evaluation"] = self.evaluation
        if self.score is not None:
            value["score"] = {"kind": self.score_kind, "value": self.score}
        if self.reason:
            value["reason"] = self.reason
        if self.basis:
            value["basis"] = list(self.basis)
        return value


@dataclass(frozen=True)
class CandidateSet:
    candidates: tuple[SearchCandidate, ...]
    scanned: int
    complete: bool = True
    stages: tuple[str, ...] = ()
    missing_stages: tuple[str, ...] = ()


@dataclass(frozen=True)
class SearchCoverage:
    scanned: int
    eligible: int
    candidates: int
    evaluated: int
    selected: int
    retained: int
    omitted_candidates: int = 0
    source_complete: bool = True
    stages: tuple[str, ...] = ()
    missing_stages: tuple[str, ...] = ()
    step_stats: tuple[JsonObject, ...] = ()
    final_count: int | None = None

    def to_json(self) -> JsonObject:
        return {"scanned": self.scanned, "eligible": self.eligible, "candidates": self.candidates, "evaluated": self.evaluated, "selected": self.selected, "retained": self.retained, "omitted_candidates": self.omitted_candidates, "source_complete": self.source_complete, "stages": list(self.stages), "missing_stages": list(self.missing_stages), "steps": list(self.step_stats), "final_count": self.final_count if self.final_count is not None else self.retained}


@dataclass(frozen=True)
class SearchPage:
    scope: str | ResourceScope
    source: SourceKind
    items: tuple[SearchCandidate, ...]
    coverage: SearchCoverage
    offset: int = 0
    continuation: str | None = None
    result_ref: str | None = None

    def to_json(self) -> JsonObject:
        total = self.coverage.final_count if self.coverage.final_count is not None else self.coverage.retained
        return {"result_ref": self.result_ref, "scope": self.scope.to_json() if isinstance(self.scope, ResourceScope) else self.scope, "source": self.source.value, "items": [item.to_json(rank=self.offset + index + 1) for index, item in enumerate(self.items)], "coverage": {**self.coverage.to_json(), "shown": self.offset + len(self.items), "remaining": max(0, total - self.offset - len(self.items))}, "page": {"offset": self.offset, "count": len(self.items), "total": total, "continuation": self.continuation}, "continuation": self.continuation}
