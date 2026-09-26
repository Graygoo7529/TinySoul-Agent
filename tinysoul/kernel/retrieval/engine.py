"""One finite search operation and a bounded, lifecycle-local immutable page store."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
import json
import re
from typing import Protocol
from uuid import uuid4
from copy import deepcopy
from time import monotonic

from tinysoul.infra.model_services.protocol import ModelServiceError
from tinysoul.infra.model_services.service import ModelObserver
from tinysoul.infra.json import JsonObject
from .contracts import (
    SearchCandidate,
    SourceKind,
    ResourceScope,
    SearchCoverage,
    SearchEvidence,
    SearchFailure,
    SearchFailureKind,
    SearchPage,
    CandidateSet,
    RetrievalRequest,
    FilterStep,
    ModelStep,
)


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
            raise SearchFailure(SearchFailureKind.SCOPE_REQUIRED, "Result exceeds the search view capacity")
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
        while len(self._views) > self._max_views or sum(view.size_chars for view in self._views.values()) > self._max_chars:
            stale, _ = self._views.popitem(last=False)
            self._positions = {
                token: value
                for token, value in self._positions.items()
                if value[0] != stale
            }
        return self._page(identity, 0)

    def result(self, result_ref: str) -> tuple[SearchCandidate, ...]:
        identity = result_ref.removeprefix("search-result:")
        view = self._views.get(identity)
        if view is None:
            raise SearchFailure(SearchFailureKind.VIEW_EXPIRED, "Search result view expired; start a new search")
        return deepcopy(view.candidates)

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
        items: list[SearchCandidate] = []
        for original in view.candidates[offset:]:
            candidate = bound_evidence(original, "", min(2_000, view.page_max_chars // 3))
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
        apply_operation: Callable[[ModelStep, tuple[SearchCandidate, ...]], Awaitable[tuple[SearchCandidate, ...]]],
        supported_filters: frozenset[str] = frozenset(),
        ordered_filters: frozenset[str] = frozenset(),
        observe_step: Callable[[JsonObject], None] | None = None,
    ) -> SearchPage:
        """Run one source snapshot through the finite registered operation list."""
        from .requests import eligible

        for step in request.steps:
            if isinstance(step, FilterStep):
                eligible({}, step.where, supported=supported_filters, ordered=ordered_filters)
        candidates = deduplicate(corpus.candidates)
        if request.exclude_refs:
            excluded = set(request.exclude_refs)
            candidates = tuple(item for item in candidates if item.ref not in excluded)
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
                candidates = tuple(
                    item for item in candidates
                    if eligible(item.attributes, step.where, supported=supported_filters, ordered=ordered_filters)
                )
                stats.append({"step_index": index, "op": step.op.value, "input": before, "output": len(candidates)})
                stages.append(step.op.value)
                if observe_step:
                    observe_step({**stats[-1], "elapsed_seconds": monotonic() - started})
                continue
            if not candidates:
                stats.append({"step_index": index, "op": step.op.value, "input": 0, "evaluated": 0, "output": 0})
                continue
            try:
                candidates = await apply_operation(step, candidates)
            except SearchFailure as exc:
                if exc.step:
                    raise
                raise SearchFailure(exc.kind, str(exc), step=step.op.value) from exc
            candidates = tuple(replace(item, evaluation={**item.evaluation, "step_index": index, "op": step.op.value}) for item in candidates)
            evaluated += before
            selected = len(candidates)
            stats.append({"step_index": index, "op": step.op.value, "input": before, "evaluated": before, "output": len(candidates)})
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


def lexical_score(query: str, text: str) -> float:
    normalized = text.casefold()
    tokens = re.findall(r"[\w]+", query.casefold())
    # Overlapping CJK pairs preserve useful matching without a language-specific index.
    terms = set(tokens)
    for token in tokens:
        if any("\u3400" <= char <= "\u9fff" for char in token):
            terms.update(token[i : i + 2] for i in range(len(token) - 1))
    return float(sum(min(normalized.count(term), 8) for term in terms))


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
                content_units=tuple({unit.id: unit for unit in (*previous.content_units, *item.content_units)}.values()),
                evidence_complete=previous.evidence_complete and item.evidence_complete,
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
                evidence = (*previous.evidence[:1], *candidate.evidence[:1], *previous.evidence[1:], *candidate.evidence[1:])
                merged: dict[str, SearchEvidence] = {}
                for unit in evidence:
                    key = unit.unit_id or unit.ref
                    known = merged.get(key)
                    merged[key] = unit if known is None else replace(known, basis=tuple(dict.fromkeys((*known.basis, *unit.basis))))
                candidates[candidate.ref] = replace(previous, evidence=tuple(merged.values()), basis=tuple(dict.fromkeys((*previous.basis, *candidate.basis))))
            scores[candidate.ref] = scores.get(candidate.ref, 0) + 1 / (60 + rank)
    return tuple(
        replace(candidates[ref], score_kind="rrf", score=scores[ref])
        for ref in sorted(candidates, key=lambda ref: -scores[ref])
    )


def bound_evidence(
    candidate: SearchCandidate, query: str, budget: int
) -> SearchCandidate:
    ordered = (
        sorted(
            candidate.evidence,
            key=lambda evidence: -lexical_score(query, evidence.text),
        )
        if query
        else candidate.evidence
    )
    evidence = []
    remaining = budget
    for item in ordered:
        if remaining <= 0:
            break
        text = item.text
        if len(text) > remaining:
            terms = re.findall(r"\w+", query.casefold())
            positions = [
                text.casefold().find(term) for term in terms if term in text.casefold()
            ]
            start = max(0, min(positions) - remaining // 3) if positions else 0
            text = (
                ("..." if start else "")
                + text[start : start + max(1, remaining - 2)]
                + "..."
            )
        evidence.append(SearchEvidence(item.ref, text, item.relation, item.unit_id, item.basis))
        remaining -= len(text)
    originals = {unit.id: unit for unit in candidate.content_units}
    units = tuple(
        replace(originals[item.unit_id], text=item.text,
                complete=originals[item.unit_id].complete and item.text == originals[item.unit_id].text)
        for item in evidence if item.unit_id in originals
    )
    return replace(
        candidate,
        evidence=tuple(evidence),
        content_units=units,
        evidence_complete=candidate.evidence_complete
        and sum(len(item.text) for item in candidate.evidence) <= budget,
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
    documents = {unit.id: unit.text for item in candidates for unit in item.content_units}
    scores = await embedding.similarities(query, documents, consumer=consumer, observer=observer) if documents else {}
    if set(scores) != set(documents):
        raise SearchFailure(SearchFailureKind.OPERATION_FAILED, "Embedding response does not cover all content units")
    ranked = []
    for item in candidates:
        units = tuple(sorted(item.content_units, key=lambda unit: -scores[unit.id]))
        evidence = tuple(SearchEvidence(unit.ref, unit.text, unit.kind, unit.id, ("embedding",)) for unit in units)
        ranked.append(replace(item, evidence=evidence, score_kind="cosine", score=max(scores[unit.id] for unit in units), basis=tuple(dict.fromkeys((*item.basis, "embedding")))))
    return tuple(sorted(ranked, key=lambda item: -(item.score or 0.0)))

def snapshot_size(candidates: tuple[SearchCandidate, ...]) -> int:
    return len(json.dumps(
        [{"candidate": item.to_json(rank=index + 1), "content": [unit.to_json() for unit in item.content_units]} for index, item in enumerate(candidates)],
        ensure_ascii=False,
    ))
