"""Typed retrieval sources, candidate operations and bounded result views."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import TypeAlias

from tinysoul.prompts.kernel import retrieval as prompt_text
from tinysoul.infra.json import JsonObject, JsonValue, to_json_object


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


class AttributeKind(StrEnum):
    TEXT = "text"
    TEXT_SET = "text_set"
    DATE = "date"


@dataclass(frozen=True)
class AttributeField:
    name: str
    kind: AttributeKind = AttributeKind.TEXT

    def schema(self) -> JsonObject:
        scalar: JsonObject = {"type": "string"}
        if self.kind is AttributeKind.DATE:
            scalar.update(
                {
                    "description": prompt_text.CALENDAR_DATE_IN_YYYY_MM_DD_FORM,
                    "minLength": 10,
                    "maxLength": 10,
                }
            )
        variants: list[JsonValue] = [
            scalar,
            {"type": "array", "items": scalar, "minItems": 1},
        ]
        if self.kind is AttributeKind.DATE:
            variants.extend(
                [
                    {
                        "type": "object",
                        "properties": {"before": scalar, "after": scalar},
                        "required": ["before"],
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {"after": scalar},
                        "required": ["after"],
                        "additionalProperties": False,
                    },
                ]
            )
        return {"oneOf": variants}


@dataclass(frozen=True)
class AttributePredicate:
    field: AttributeField
    values: tuple[str, ...] = ()
    before: str | None = None
    after: str | None = None

    def matches(self, attributes: JsonObject) -> bool:
        actual = attributes.get(self.field.name)
        if self.field.kind is AttributeKind.TEXT_SET:
            return isinstance(actual, list) and all(
                value in actual for value in self.values
            )
        if not isinstance(actual, str):
            return False
        return (
            (not self.values or actual in self.values)
            and (self.before is None or actual < self.before)
            and (self.after is None or actual > self.after)
        )


@dataclass(frozen=True)
class AttributeFilters:
    fields: tuple[AttributeField, ...] = ()

    def schema(self) -> JsonObject:
        return {
            "type": "object",
            "properties": {field.name: field.schema() for field in self.fields},
            "additionalProperties": False,
        }

    def parse(self, where: JsonObject) -> tuple[AttributePredicate, ...]:
        fields = {field.name: field for field in self.fields}
        result = []
        for name, value in where.items():
            field = fields.get(name)
            if field is None:
                raise SearchFailure(
                    SearchFailureKind.INVALID_REQUEST,
                    prompt_text.THIS_SOURCE_DOES_NOT_SUPPORT_THE_REQUESTED_FILTER,
                )
            if isinstance(value, dict):
                if (
                    field.kind is not AttributeKind.DATE
                    or not value
                    or set(value) - {"before", "after"}
                ):
                    raise SearchFailure(
                        SearchFailureKind.INVALID_REQUEST,
                        prompt_text.INVALID_ORDERED_FILTER,
                    )
                values = list(value.values())
            else:
                values = value if isinstance(value, list) else [value]
            if not values or any(not isinstance(item, str) for item in values):
                raise SearchFailure(
                    SearchFailureKind.INVALID_REQUEST,
                    prompt_text.FILTER_REQUIRES_TEXT_VALUES,
                )
            checked = tuple(item for item in values if isinstance(item, str))
            if field.kind is AttributeKind.DATE:
                try:
                    if any(
                        date.fromisoformat(item).isoformat() != item for item in checked
                    ):
                        raise ValueError("Noncanonical date")
                except ValueError as exc:
                    raise SearchFailure(
                        SearchFailureKind.INVALID_REQUEST,
                        prompt_text.DATE_FILTER_REQUIRES_YYYY_MM_DD,
                    ) from exc
            if isinstance(value, dict):
                before, after = value.get("before"), value.get("after")
                result.append(
                    AttributePredicate(
                        field,
                        before=before if isinstance(before, str) else None,
                        after=after if isinstance(after, str) else None,
                    )
                )
            else:
                result.append(AttributePredicate(field, checked))
        return tuple(result)


class SearchFailureKind(StrEnum):
    INVALID_REQUEST = "invalid_request"
    SCOPE_REQUIRED = "scope_required"
    SOURCE_UNAVAILABLE = "source_unavailable"
    OPERATION_FAILED = "operation_failed"
    VIEW_EXPIRED = "view_expired"


class SearchFailure(Exception):
    """A finite retrieval failure mapped by an Action or SDK boundary."""

    def __init__(
        self, kind: SearchFailureKind, message: str, *, step: str = ""
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.step = step


@dataclass(frozen=True)
class TextQuery:
    text: str

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST, prompt_text.QUERY_MUST_NOT_BE_EMPTY
            )


@dataclass(frozen=True)
class DocumentQuery:
    document_ref: str

    def __post_init__(self) -> None:
        if not self.document_ref:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                prompt_text.DOCUMENT_QUERY_REQUIRES_AN_IDENTITY,
            )


class ResourceScopeKind(StrEnum):
    WORKSPACE = "workspace"
    DIRECTORY = "directory"
    FILE = "file"


@dataclass(frozen=True)
class ResourceScope:
    kind: ResourceScopeKind
    ref: str | None = None

    def __post_init__(self) -> None:
        valid = (
            self.ref is None
            if self.kind is ResourceScopeKind.WORKSPACE
            else isinstance(self.ref, str)
            and self.ref.startswith("workspace:")
            and self.ref != "workspace:"
        )
        if not valid:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST, prompt_text.INVALID_RESOURCE_SCOPE
            )

    def to_json(self) -> JsonObject:
        return {
            "kind": self.kind.value,
            **({"ref": self.ref} if self.ref is not None else {}),
        }


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
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                prompt_text.QUERY_SOURCE_REQUIRES_A_SCOPE,
            )
        object.__setattr__(self, "where", to_json_object(self.where))


@dataclass(frozen=True)
class BacklinksSource:
    scope: str | ResourceScope
    anchor_ref: str
    where: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.scope or not self.anchor_ref:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                prompt_text.BACKLINKS_SOURCE_REQUIRES_SCOPE_AND_ANCHOR_REF,
            )
        object.__setattr__(self, "where", to_json_object(self.where))


@dataclass(frozen=True)
class DirectorySource:
    scope: str | ResourceScope
    where: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.scope:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                prompt_text.DIRECTORY_SOURCE_REQUIRES_A_SCOPE,
            )
        object.__setattr__(self, "where", to_json_object(self.where))


@dataclass(frozen=True)
class RefsSource:
    refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.refs or any(not ref for ref in self.refs):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                prompt_text.REFS_SOURCE_REQUIRES_NON_EMPTY_REFS,
            )


@dataclass(frozen=True)
class ResultSource:
    result_handle: str

    def __post_init__(self) -> None:
        if not self.result_handle:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                prompt_text.RESULT_SOURCE_REQUIRES_RESULT_REF,
            )


SearchSource: TypeAlias = (
    QuerySource | BacklinksSource | DirectorySource | RefsSource | ResultSource
)


@dataclass(frozen=True)
class FilterStep:
    where: JsonObject
    op: OperationKind = field(default=OperationKind.FILTER, init=False)

    def __post_init__(self) -> None:
        if not self.where:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                prompt_text.FILTER_REQUIRES_A_NON_EMPTY_WHERE,
            )
        object.__setattr__(self, "where", to_json_object(self.where))


@dataclass(frozen=True)
class ModelStep:
    op: OperationKind
    criterion: str
    context: SearchContext = SearchContext.NONE

    def __post_init__(self) -> None:
        if (
            self.op not in {OperationKind.SELECT, OperationKind.RERANK}
            or not self.criterion.strip()
        ):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                prompt_text.SELECT_AND_RERANK_REQUIRE_A_CRITERION,
            )


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
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                prompt_text.PAGE_LIMIT_MUST_BE_POSITIVE,
            )
        if len(set(self.exclude_refs)) != len(self.exclude_refs) or any(
            not ref for ref in self.exclude_refs
        ):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                prompt_text.EXCLUDE_REFS_MUST_CONTAIN_UNIQUE_NON_EMPTY_REFS,
            )

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

    def __post_init__(self) -> None:
        if not self.id or not self.ref or not isinstance(self.text, str):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "ContentUnit requires id, ref and text",
            )
        object.__setattr__(self, "location", to_json_object(self.location))

    def to_json(self) -> JsonObject:
        return {
            "id": self.id,
            "ref": self.ref,
            "text": self.text,
            "kind": self.kind,
            "location": self.location,
        }


class ContentCoverage(StrEnum):
    FULL = "full"
    EXCERPT = "excerpt"
    METADATA = "metadata"


class EvidenceKind(StrEnum):
    LEXICAL = "lexical"
    EMBEDDING = "embedding"
    REFERENCE = "reference"
    MODEL = "model"


@dataclass(frozen=True)
class SearchEvidence:
    unit_id: str
    kind: EvidenceKind
    start: int = 0
    end: int | None = None
    relation: str | None = None

    def __post_init__(self) -> None:
        if (
            not self.unit_id
            or self.start < 0
            or (self.end is not None and self.end < self.start)
        ):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Evidence requires a content identity and valid range",
            )

    def to_json(self) -> JsonObject:
        return {
            "unit_id": self.unit_id,
            "kind": self.kind.value,
            "start": self.start,
            "end": self.end,
            "relation": self.relation,
        }


@dataclass(frozen=True)
class ModelEvaluation:
    op: OperationKind
    input_coverage: ContentCoverage
    basis: tuple[SearchEvidence, ...] = ()
    score: float | None = None
    score_kind: str | None = None
    step_index: int = 0

    def to_json(self) -> JsonObject:
        value: JsonObject = {
            "op": self.op.value,
            "step_index": self.step_index,
            "input_coverage": self.input_coverage.value,
        }
        if self.score is not None:
            value["score"] = {"kind": self.score_kind, "value": self.score}
        return value


@dataclass(frozen=True)
class SearchCandidate:
    ref: str
    title: str
    content_units: tuple[ContentUnit, ...]
    attributes: JsonObject = field(default_factory=dict)
    evidence: tuple[SearchEvidence, ...] = ()
    content_coverage: ContentCoverage = ContentCoverage.FULL
    score_kind: str | None = None
    score: float | None = None
    evaluation: ModelEvaluation | None = None

    def __post_init__(self) -> None:
        if not self.ref or not self.content_units:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Candidate requires identity and source content",
            )
        object.__setattr__(self, "attributes", to_json_object(self.attributes))
        units = {unit.id: unit for unit in self.content_units}
        if len(units) != len(self.content_units):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Candidate content identities must be unique",
            )
        for evidence in (
            *self.evidence,
            *(self.evaluation.basis if self.evaluation else ()),
        ):
            unit = units.get(evidence.unit_id)
            if (
                unit is None
                or evidence.start > len(unit.text)
                or (evidence.end is not None and evidence.end > len(unit.text))
            ):
                raise SearchFailure(
                    SearchFailureKind.INVALID_REQUEST,
                    "Evidence is outside candidate content",
                )


@dataclass(frozen=True)
class ContentSlice:
    """A projection points into immutable content; it never owns another text copy."""

    unit: ContentUnit
    start: int
    end: int
    evidence: tuple[SearchEvidence, ...] = ()

    @property
    def basis(self) -> tuple[EvidenceKind, ...]:
        return tuple(dict.fromkeys(hit.kind for hit in self.evidence))

    @property
    def text(self) -> str:
        return self.unit.text[self.start : self.end]

    def to_json(self) -> JsonObject:
        location = dict(self.unit.location)
        line = location.get("line")
        if type(line) is int:
            prefix = self.unit.text[: self.start]
            first_line = line + prefix.count("\n")
            location["line"] = first_line
            location["end_line"] = first_line + self.text.rstrip("\r\n").count("\n")
            column = location.get("column", 1)
            location["column"] = len(prefix.rsplit("\n", 1)[-1]) + (
                1 if "\n" in prefix else int(column) if type(column) is int else 1
            )
        location["unit_start"] = self.start
        location["unit_end"] = self.end
        return {
            "ref": self.unit.ref,
            "text": self.text,
            "kind": self.unit.kind,
            "location": location,
            "basis": [kind.value for kind in self.basis],
            "matches": [
                {
                    "kind": hit.kind.value,
                    "start": max(self.start, hit.start) - self.start,
                    "end": min(
                        self.end,
                        hit.end if hit.end is not None else len(self.unit.text),
                    )
                    - self.start,
                    "relation": hit.relation,
                }
                for hit in self.evidence
            ],
        }


@dataclass(frozen=True)
class CandidatePreview:
    candidate: SearchCandidate
    fragments: tuple[ContentSlice, ...]
    coverage: ContentCoverage

    @property
    def ref(self) -> str:
        return self.candidate.ref

    def to_json(self, *, rank: int) -> JsonObject:
        item = self.candidate
        value: JsonObject = {
            "ref": item.ref,
            "title": item.title,
            "rank": rank,
            "evidence": [part.to_json() for part in self.fragments],
            "content_coverage": item.content_coverage.value,
            "preview_coverage": self.coverage.value,
            "attributes": item.attributes,
        }
        if item.evaluation is not None:
            value["evaluation"] = item.evaluation.to_json()
        if item.score is not None:
            value["source_score"] = {"kind": item.score_kind, "value": item.score}
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
        return {
            "scanned": self.scanned,
            "eligible": self.eligible,
            "candidates": self.candidates,
            "evaluated": self.evaluated,
            "selected": self.selected,
            "retained": self.retained,
            "omitted_candidates": self.omitted_candidates,
            "source_complete": self.source_complete,
            "stages": list(self.stages),
            "missing_stages": list(self.missing_stages),
            "steps": list(self.step_stats),
            "final_count": self.final_count
            if self.final_count is not None
            else self.retained,
        }


@dataclass(frozen=True)
class SearchPage:
    scope: str | ResourceScope
    source: SourceKind
    items: tuple[CandidatePreview, ...]
    coverage: SearchCoverage
    offset: int = 0
    continuation: str | None = None
    result_handle: str | None = None

    def recollection(self) -> JsonObject:
        """Keep each selected reference with its real title and bounded excerpt."""
        return {
            "source": self.source.value,
            "selected": [
                {
                    "ref": item.ref,
                    "title": item.candidate.title,
                    "excerpt": " ".join(part.text for part in item.fragments)[:240],
                }
                for item in self.items
            ],
        }

    def to_json(self) -> JsonObject:
        total = (
            self.coverage.final_count
            if self.coverage.final_count is not None
            else self.coverage.retained
        )
        return {
            "result_handle": self.result_handle,
            "scope": self.scope.to_json()
            if isinstance(self.scope, ResourceScope)
            else self.scope,
            "source": self.source.value,
            "items": [
                item.to_json(rank=self.offset + index + 1)
                for index, item in enumerate(self.items)
            ],
            "coverage": {
                **self.coverage.to_json(),
                "shown": self.offset + len(self.items),
                "remaining": max(0, total - self.offset - len(self.items)),
            },
            "page": {
                "offset": self.offset,
                "count": len(self.items),
                "total": total,
                "continuation": self.continuation,
            },
            "continuation": self.continuation,
        }
