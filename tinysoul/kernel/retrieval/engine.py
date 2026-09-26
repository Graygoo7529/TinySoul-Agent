"""One finite search operation and a bounded, lifecycle-local immutable page store."""

from __future__ import annotations

import json
import re
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
from time import monotonic
from typing import Protocol
from uuid import uuid4

import regex

from tinysoul.infra.json import JsonObject
from tinysoul.infra.model_services.service import ModelObserver

from .contracts import (
    AttributeFilters,
    CandidatePreview,
    CandidateSet,
    ContentUnit,
    EvidenceKind,
    FilterStep,
    ModelStep,
    QuerySource,
    ResourceScope,
    RetrievalRequest,
    SearchCandidate,
    SearchCoverage,
    SearchEvidence,
    SearchFailure,
    SearchFailureKind,
    SearchPage,
    SourceKind,
)
from .disclosure import project_candidate, range_evidence


class VectorSource(Protocol):
    async def similarities(
        self,
        query: str,
        documents: Mapping[str, str],
        *,
        consumer: str = "embedding",
        observer: ModelObserver | None = None,
    ) -> Mapping[str, float]: ...


@dataclass(frozen=True)
class _SearchView:
    scope: str | ResourceScope
    source: SourceKind
    candidates: tuple[SearchCandidate, ...]
    coverage: SearchCoverage
    page_max_chars: int
    page_max_items: int | None
    size_chars: int


class SearchViews:
    """Owned by a Turn/profile or leased SDK query scope, never a persistent index."""

    def __init__(self, *, max_views: int = 16, max_chars: int = 16_000_000) -> None:
        self._max_views, self._max_chars = max_views, max_chars
        self._views: OrderedDict[str, _SearchView] = OrderedDict()
        self._positions: dict[str, tuple[str, int]] = {}

    def close(self) -> None:
        self._views.clear()
        self._positions.clear()

    def create(
        self,
        request: RetrievalRequest,
        candidates: tuple[SearchCandidate, ...],
        coverage: SearchCoverage,
        *,
        page_max_chars: int,
        page_max_items: int | None = None,
    ) -> SearchPage:
        size = snapshot_size(candidates)
        if size > self._max_chars:
            raise SearchFailure(
                SearchFailureKind.SCOPE_REQUIRED,
                "Result exceeds the search view capacity",
            )
        identity = uuid4().hex
        scope = getattr(request.source, "scope", request.source_kind.value)
        self._views[identity] = _SearchView(
            scope,
            request.source_kind,
            deepcopy(candidates),
            coverage,
            page_max_chars,
            page_max_items,
            size,
        )
        while (
            len(self._views) > self._max_views
            or sum(view.size_chars for view in self._views.values()) > self._max_chars
        ):
            stale, _ = self._views.popitem(last=False)
            self._positions = {
                token: value
                for token, value in self._positions.items()
                if value[0] != stale
            }
        return self._page(identity, 0)

    def result(self, result_ref: str) -> CandidateSet:
        identity = result_ref.removeprefix("search-result:")
        view = self._views.get(identity)
        if view is None:
            raise SearchFailure(
                SearchFailureKind.VIEW_EXPIRED,
                "Search result view expired; start a new search",
            )
        return CandidateSet(
            tuple(
                replace(item, evaluation=None, score=None, score_kind=None)
                for item in deepcopy(view.candidates)
            ),
            view.coverage.scanned,
            view.coverage.source_complete,
            tuple(
                stage
                for stage in view.coverage.stages
                if stage not in {"filter", "select", "rerank"}
            ),
            view.coverage.missing_stages,
        )

    def resume(self, continuation: str) -> SearchPage:
        position = self._positions.get(continuation)
        if position is None or position[0] not in self._views:
            raise SearchFailure(
                SearchFailureKind.VIEW_EXPIRED,
                "Search continuation expired; start a new search",
            )
        return self._page(*position)

    def _page(self, identity: str, offset: int) -> SearchPage:
        view = self._views[identity]
        items: list[CandidatePreview] = []
        for original in view.candidates[offset:]:
            candidate = project_candidate(
                original, min(2_000, view.page_max_chars // 3)
            )
            if view.page_max_items is not None and len(items) >= view.page_max_items:
                break
            proposed = SearchPage(
                view.scope,
                view.source,
                (*items, candidate),
                view.coverage,
                offset,
                "x" * 32,
                f"search-result:{identity}",
            )
            if (
                len(json.dumps(proposed.to_json(), ensure_ascii=False))
                > view.page_max_chars
            ):
                if not items:
                    raise SearchFailure(
                        SearchFailureKind.SCOPE_REQUIRED,
                        "One candidate exceeds the configured page budget",
                    )
                break
            items.append(candidate)
        next_offset = offset + len(items)
        continuation = None
        if next_offset < len(view.candidates):
            # Replaying a page gives the same successor; token state stays bounded.
            continuation = next(
                (
                    token
                    for token, position in self._positions.items()
                    if position == (identity, next_offset)
                ),
                None,
            )
            if continuation is None:
                continuation = uuid4().hex
                self._positions[continuation] = (identity, next_offset)
        return SearchPage(
            view.scope,
            view.source,
            deepcopy(tuple(items)),
            view.coverage,
            offset,
            continuation,
            f"search-result:{identity}",
        )


class SearchEngine:
    """Compose configured recall sources and one typed semantic operation."""

    def __init__(
        self, *, views: SearchViews, embedding: VectorSource | None = None
    ) -> None:
        self.views, self.embedding = views, embedding

    async def compose(
        self,
        request: RetrievalRequest,
        *,
        corpus: CandidateSet,
        page_max_chars: int,
        snapshot_max_chars: int = 4_000_000,
        apply_operation: Callable[
            [int, ModelStep, tuple[SearchCandidate, ...]],
            Awaitable[tuple[SearchCandidate, ...]],
        ],
        filters: AttributeFilters = AttributeFilters(),
        observe_step: Callable[[JsonObject], None] | None = None,
    ) -> SearchPage:
        """Run one source snapshot through the finite registered operation list."""
        candidates = deduplicate(corpus.candidates)
        initial = len(candidates)
        stats: list[JsonObject] = []
        evaluated = 0
        selected = len(candidates)
        stages = list(corpus.stages)
        missing = list(corpus.missing_stages)
        for index, step in enumerate(request.steps):
            started = monotonic()
            before = len(candidates)
            if isinstance(step, FilterStep):
                predicates = filters.parse(step.where)
                candidates = tuple(
                    item
                    for item in candidates
                    if all(
                        predicate.matches(item.attributes) for predicate in predicates
                    )
                )
                stats.append(
                    {
                        "step_index": index,
                        "op": step.op.value,
                        "input": before,
                        "output": len(candidates),
                    }
                )
                stages.append(step.op.value)
                if observe_step:
                    observe_step(
                        {**stats[-1], "elapsed_seconds": monotonic() - started}
                    )
                continue
            if not candidates:
                stats.append(
                    {
                        "step_index": index,
                        "op": step.op.value,
                        "input": 0,
                        "evaluated": 0,
                        "output": 0,
                    }
                )
                stages.append(step.op.value)
                if observe_step:
                    observe_step(
                        {**stats[-1], "elapsed_seconds": monotonic() - started}
                    )
                continue
            try:
                candidates = await apply_operation(index, step, candidates)
            except SearchFailure as exc:
                if exc.step:
                    raise
                raise SearchFailure(exc.kind, str(exc), step=step.op.value) from exc
            candidates = tuple(
                replace(item, evaluation=replace(item.evaluation, step_index=index))
                if item.evaluation
                else item
                for item in candidates
            )
            evaluated += before
            selected = len(candidates)
            stats.append(
                {
                    "step_index": index,
                    "op": step.op.value,
                    "input": before,
                    "evaluated": before,
                    "output": len(candidates),
                }
            )
            stages.append(step.op.value)
            if observe_step:
                observe_step({**stats[-1], "elapsed_seconds": monotonic() - started})
        final_count = len(candidates)
        selected = final_count
        if snapshot_size(candidates) > snapshot_max_chars:
            raise SearchFailure(
                SearchFailureKind.SCOPE_REQUIRED,
                "Search result snapshot exceeds its configured budget; narrow the source or pipeline",
            )
        coverage = SearchCoverage(
            scanned=corpus.scanned,
            eligible=initial,
            candidates=initial,
            evaluated=evaluated,
            selected=selected,
            retained=final_count,
            omitted_candidates=0,
            source_complete=corpus.complete,
            stages=tuple(stages),
            missing_stages=tuple(missing),
            step_stats=tuple(stats),
            final_count=final_count,
        )
        # SearchViews owns the complete final set.  Its page budget is applied
        # only while constructing the first/next page.
        return self.views.create(
            request,
            candidates,
            coverage,
            page_max_chars=page_max_chars,
            page_max_items=request.page_limit,
        )


def lexical_rank(
    source: QuerySource, query: str, candidates: tuple[SearchCandidate, ...]
) -> tuple[SearchCandidate, ...]:
    """Match original resource text, not a concatenation of display snippets."""
    if source.regex:
        expression = query
    elif source.literal or source.case_sensitive:
        expression = regex.escape(query)
    else:
        terms = set(re.findall(r"[\w]+", query))
        for token in tuple(terms):
            if any("\u3400" <= char <= "\u9fff" for char in token):
                terms.update(
                    token[index : index + 2] for index in range(len(token) - 1)
                )
        expression = "|".join(
            regex.escape(term)
            for term in sorted(terms, key=lambda term: (-len(term), term))
        )
    if not expression:
        return ()
    try:
        pattern = regex.compile(
            expression, flags=0 if source.case_sensitive else regex.IGNORECASE
        )
    except regex.error as exc:
        raise SearchFailure(
            SearchFailureKind.INVALID_REQUEST, "Query regex is invalid"
        ) from exc
    ranked = []
    for candidate in candidates:
        resources: dict[str, list[ContentUnit]] = {}
        for unit in candidate.content_units:
            resources.setdefault(unit.ref.partition("#")[0], []).append(unit)
        hits: list[SearchEvidence] = []
        score = 0
        try:
            for resource_units in resources.values():
                text = "".join(unit.text for unit in resource_units)
                for match in pattern.finditer(text, timeout=0.2):
                    hits.extend(
                        range_evidence(
                            tuple(resource_units),
                            match.start(),
                            max(match.end(), match.start() + 1),
                            kind=EvidenceKind.LEXICAL,
                        )
                    )
                    score += 1
        except TimeoutError as exc:
            raise SearchFailure(
                SearchFailureKind.SCOPE_REQUIRED,
                "Query matching exceeded its budget; simplify the pattern",
            ) from exc
        if score:
            ranked.append(
                replace(
                    candidate,
                    evidence=(*candidate.evidence, *hits),
                    score_kind="lexical",
                    score=float(score),
                )
            )
    return tuple(sorted(ranked, key=lambda item: -(item.score or 0)))


def deduplicate(candidates: tuple[SearchCandidate, ...]) -> tuple[SearchCandidate, ...]:
    by_ref: dict[str, SearchCandidate] = {}
    for item in candidates:
        previous = by_ref.get(item.ref)
        by_ref[item.ref] = (
            item
            if previous is None
            else replace(
                previous,
                evidence=tuple(dict.fromkeys((*previous.evidence, *item.evidence))),
                content_units=tuple(
                    {
                        unit.id: unit
                        for unit in (*previous.content_units, *item.content_units)
                    }.values()
                ),
            )
        )
    return tuple(by_ref.values())


def fuse(rankings: list[tuple[SearchCandidate, ...]]) -> tuple[SearchCandidate, ...]:
    if len(rankings) == 1:
        return rankings[0]
    scores: dict[str, float] = {}
    candidates: dict[str, SearchCandidate] = {}
    for ranking in rankings:
        for rank, candidate in enumerate(ranking, 1):
            previous = candidates.get(candidate.ref)
            if previous is None:
                candidates[candidate.ref] = candidate
            else:
                candidates[candidate.ref] = replace(
                    previous,
                    evidence=tuple(
                        dict.fromkeys((*previous.evidence, *candidate.evidence))
                    ),
                )
            scores[candidate.ref] = scores.get(candidate.ref, 0) + 1 / (60 + rank)
    return tuple(
        replace(candidates[ref], score_kind="rrf", score=scores[ref])
        for ref in sorted(candidates, key=lambda ref: -scores[ref])
    )


async def embedding_rank(
    embedding: VectorSource,
    query: str,
    candidates: tuple[SearchCandidate, ...],
    *,
    consumer: str,
    observer: ModelObserver | None = None,
) -> tuple[SearchCandidate, ...]:
    """Use the same content units for retrieval, reranking, and hit previews."""
    documents = {
        unit.id: unit.text for item in candidates for unit in item.content_units
    }
    scores = (
        await embedding.similarities(
            query, documents, consumer=consumer, observer=observer
        )
        if documents
        else {}
    )
    if set(scores) != set(documents):
        raise SearchFailure(
            SearchFailureKind.OPERATION_FAILED,
            "Embedding response does not cover all content units",
        )
    ranked = []
    for item in candidates:
        units = tuple(sorted(item.content_units, key=lambda unit: -scores[unit.id]))
        evidence = tuple(
            SearchEvidence(unit.id, EvidenceKind.EMBEDDING) for unit in units
        )
        ranked.append(
            replace(
                item,
                evidence=(*item.evidence, *evidence),
                score_kind="cosine",
                score=max(scores[unit.id] for unit in units),
            )
        )
    return tuple(sorted(ranked, key=lambda item: -(item.score or 0.0)))


def snapshot_size(candidates: tuple[SearchCandidate, ...]) -> int:
    return len(
        json.dumps(
            [
                {
                    "ref": item.ref,
                    "title": item.title,
                    "attributes": item.attributes,
                    "evidence": [hit.to_json() for hit in item.evidence],
                    "evaluation": item.evaluation.to_json()
                    if item.evaluation
                    else None,
                    "basis": [hit.to_json() for hit in item.evaluation.basis]
                    if item.evaluation
                    else [],
                    "content": [unit.to_json() for unit in item.content_units],
                }
                for item in candidates
            ],
            ensure_ascii=False,
        )
    )
