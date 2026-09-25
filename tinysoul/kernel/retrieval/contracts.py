"""Owner-neutral search requests, bounded evidence and observable coverage."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from tinysoul.infra.json import JsonObject, to_json_object


class SearchMode(StrEnum):
    QUERY_DISCOVERY = "query_discovery"
    SEED_REFINEMENT = "seed_refinement"
    BACKLINK_SEARCH = "backlink_search"


class SearchSemantic(StrEnum):
    NONE = "none"
    RANK = "rank"
    SELECT = "select"


class SearchContext(StrEnum):
    NONE = "none"
    CURRENT = "current"


class CandidateSource(StrEnum):
    LEXICAL = "lexical"
    EMBEDDING = "embedding"


class SearchFailureKind(StrEnum):
    INVALID_REQUEST = "invalid_request"
    SCOPE_REQUIRED = "scope_required"
    SOURCE_UNAVAILABLE = "source_unavailable"
    SELECTION_FAILED = "selection_failed"
    CONTINUATION_EXPIRED = "continuation_expired"


class SearchFailure(Exception):
    """A finite operation failure mapped by an Action or SDK boundary."""

    def __init__(self, kind: SearchFailureKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class SearchOptions:
    scope: str
    semantic: SearchSemantic = SearchSemantic.NONE
    context: SearchContext = SearchContext.NONE
    limit: int = 20
    filters: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.scope or type(self.limit) is not int or self.limit < 1:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Search requires a scope and positive result limit",
            )
        object.__setattr__(self, "filters", to_json_object(self.filters))


@dataclass(frozen=True)
class TextQuery:
    text: str

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST, "Search query must not be empty"
            )


@dataclass(frozen=True)
class DocumentQuery:
    document_ref: str

    def __post_init__(self) -> None:
        if not self.document_ref:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST, "Document query requires an identity"
            )


@dataclass(frozen=True)
class QueryDiscovery:
    query: TextQuery | DocumentQuery
    options: SearchOptions
    mode: SearchMode = field(default=SearchMode.QUERY_DISCOVERY, init=False)


@dataclass(frozen=True)
class SeedRefinement:
    query: str
    options: SearchOptions
    seed_refs: tuple[str, ...] = ()
    directory: bool = False
    mode: SearchMode = field(default=SearchMode.SEED_REFINEMENT, init=False)

    def __post_init__(self) -> None:
        if (
            not self.query.strip()
            or (not self.seed_refs and not self.directory)
            or any(not ref for ref in self.seed_refs)
        ):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Seed refinement requires query and known refs or a declared directory",
            )
        if self.options.semantic is not SearchSemantic.SELECT:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Seed refinement requires semantic selection",
            )


@dataclass(frozen=True)
class BacklinkSearch:
    anchor_ref: str
    options: SearchOptions
    query: str = ""
    mode: SearchMode = field(default=SearchMode.BACKLINK_SEARCH, init=False)

    def __post_init__(self) -> None:
        if not self.anchor_ref:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST, "Backlink search requires an anchor"
            )
        if (
            not self.query.strip()
            and self.options.context is SearchContext.NONE
            and self.options.semantic is not SearchSemantic.NONE
        ):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Semantic backlink search requires query or current Context",
            )


SearchRequest = QueryDiscovery | SeedRefinement | BacklinkSearch


@dataclass(frozen=True)
class SearchEvidence:
    ref: str
    text: str
    relation: str = "content"

    def __post_init__(self) -> None:
        if not self.ref or not self.relation:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Evidence requires a readable identity and relation",
            )

    def to_json(self) -> JsonObject:
        return {"ref": self.ref, "text": self.text, "relation": self.relation}


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

    def __post_init__(self) -> None:
        if not self.ref or not self.evidence:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Candidate requires identity and source evidence",
            )
        object.__setattr__(self, "attributes", to_json_object(self.attributes))

    @property
    def text(self) -> str:
        return self.title + "\n" + "\n".join(item.text for item in self.evidence)

    def to_json(self, *, rank: int) -> JsonObject:
        value: JsonObject = {
            "ref": self.ref,
            "title": self.title,
            "rank": rank,
            "evidence": [item.to_json() for item in self.evidence],
            "evidence_complete": self.evidence_complete,
            "attributes": to_json_object(self.attributes),
        }
        if self.score is not None:
            value["score"] = {"kind": self.score_kind, "value": self.score}
        if self.reason:
            value["reason"] = self.reason
        return value


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

    def to_json(self) -> JsonObject:
        return {
            "scanned": self.scanned,
            "eligible": self.eligible,
            "candidates": self.candidates,
            "evaluated": self.evaluated,
            "selected": self.selected,
            "retained": self.retained,
            "omitted_candidates": self.omitted_candidates,
            "result_limit_omitted": self.selected - self.retained,
            "source_complete": self.source_complete,
            "stages": list(self.stages),
            "missing_stages": list(self.missing_stages),
        }


@dataclass(frozen=True)
class SearchPage:
    scope: str
    mode: SearchMode
    items: tuple[SearchCandidate, ...]
    coverage: SearchCoverage
    offset: int = 0
    continuation: str | None = None

    def to_json(self) -> JsonObject:
        return {
            "scope": self.scope,
            "mode": self.mode.value,
            "items": [
                item.to_json(rank=self.offset + index + 1)
                for index, item in enumerate(self.items)
            ],
            "coverage": {
                **self.coverage.to_json(),
                "shown": self.offset + len(self.items),
                "remaining": self.coverage.retained - self.offset - len(self.items),
            },
            "continuation": self.continuation,
        }
