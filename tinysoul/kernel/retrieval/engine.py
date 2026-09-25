"""One finite search operation and a bounded, lifecycle-local immutable page store."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
import json
import re
from typing import Protocol
from uuid import uuid4

from tinysoul.infra.model_services.protocol import ModelServiceError
from tinysoul.infra.model_services.service import ModelObserver
from .contracts import (
    BacklinkSearch,
    CandidateSource,
    SearchCandidate,
    SearchCoverage,
    SearchEvidence,
    SearchFailure,
    SearchFailureKind,
    SearchPage,
    SearchRequest,
    SearchSemantic,
    SearchMode,
    SeedRefinement,
)
from .policy import SearchPolicy


class VectorSource(Protocol):
    async def similarities(
        self,
        query: str,
        documents: Mapping[str, str],
        *,
        consumer: str = "embedding",
        observer: ModelObserver | None = None,
    ) -> Mapping[str, float]: ...


SemanticOperation = Callable[
    [str, tuple[SearchCandidate, ...], SearchSemantic],
    Awaitable[tuple[SearchCandidate, ...]],
]


@dataclass(frozen=True)
class _SearchView:
    scope: str
    mode: SearchMode
    candidates: tuple[SearchCandidate, ...]
    coverage: SearchCoverage
    page_max_chars: int


class SearchViews:
    """Owned by a Turn/profile or leased SDK query scope, never a persistent index."""

    def __init__(self, *, max_views: int = 16) -> None:
        self._max_views = max_views
        self._views: OrderedDict[str, _SearchView] = OrderedDict()
        self._positions: dict[str, tuple[str, int]] = {}

    def close(self) -> None:
        self._views.clear()
        self._positions.clear()

    def create(
        self,
        request: SearchRequest,
        candidates: tuple[SearchCandidate, ...],
        coverage: SearchCoverage,
        *,
        page_max_chars: int,
    ) -> SearchPage:
        identity = uuid4().hex
        self._views[identity] = _SearchView(
            request.options.scope,
            request.mode,
            tuple(replace(item) for item in candidates),
            coverage,
            page_max_chars,
        )
        while len(self._views) > self._max_views:
            stale, _ = self._views.popitem(last=False)
            self._positions = {
                token: value
                for token, value in self._positions.items()
                if value[0] != stale
            }
        return self._page(identity, 0)

    def resume(self, continuation: str) -> SearchPage:
        position = self._positions.get(continuation)
        if position is None or position[0] not in self._views:
            raise SearchFailure(
                SearchFailureKind.CONTINUATION_EXPIRED,
                "Search continuation expired; start a new search",
            )
        return self._page(*position)

    def _page(self, identity: str, offset: int) -> SearchPage:
        view = self._views[identity]
        items: list[SearchCandidate] = []
        for candidate in view.candidates[offset:]:
            proposed = SearchPage(
                view.scope,
                view.mode,
                (*items, candidate),
                view.coverage,
                offset,
                "x" * 32,
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
            view.mode,
            tuple(replace(item) for item in items),
            view.coverage,
            offset,
            continuation,
        )


class SearchEngine:
    """Compose configured recall sources and one typed semantic operation."""

    def __init__(
        self, *, views: SearchViews, embedding: VectorSource | None = None
    ) -> None:
        self.views, self.embedding = views, embedding

    async def search(
        self,
        request: SearchRequest,
        *,
        policy: SearchPolicy,
        candidates: tuple[SearchCandidate, ...],
        query: str,
        semantic: SemanticOperation | None = None,
        scanned: int | None = None,
        source_complete: bool = True,
        observer: ModelObserver | None = None,
    ) -> SearchPage:
        policy.validate(request.options)
        if request.mode is not policy.mode:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Search mode does not match its policy",
            )
        candidates = deduplicate(candidates)
        eligible = len(candidates)
        stages: list[str] = []
        missing: list[str] = []
        if request.mode is SearchMode.QUERY_DISCOVERY:
            rankings: list[tuple[SearchCandidate, ...]] = []
            for source in policy.candidate_sources:
                if source is CandidateSource.LEXICAL:
                    scored = [
                        (candidate, lexical_score(query, candidate.text))
                        for candidate in candidates
                    ]
                    ordered = sorted(
                        (pair for pair in scored if pair[1] > 0),
                        key=lambda pair: -pair[1],
                    )
                    rankings.append(
                        tuple(
                            replace(candidate, score_kind="lexical", score=score)
                            for candidate, score in ordered
                        )
                    )
                else:
                    if self.embedding is None:
                        raise SearchFailure(
                            SearchFailureKind.INVALID_REQUEST,
                            "Embedding source has no owner binding",
                        )
                    try:
                        scores = await self.embedding_scores(
                            query,
                            candidates,
                            consumer=f"{policy.action_id}.discovery",
                            observer=observer,
                        )
                    except ModelServiceError as exc:
                        if not exc.recoverable:
                            raise
                        missing.append("embedding:unavailable")
                        continue
                    rankings.append(
                        tuple(
                            replace(
                                candidate,
                                score_kind="cosine",
                                score=scores[candidate.ref],
                            )
                            for candidate in sorted(
                                candidates, key=lambda item: -scores[item.ref]
                            )
                        )
                    )
                stages.append(source.value)
            if not rankings:
                raise SearchFailure(
                    SearchFailureKind.SOURCE_UNAVAILABLE,
                    "Every configured candidate source was unavailable",
                )
            candidates = fuse(rankings)
        elif isinstance(request, BacklinkSearch):
            # The owner has already resolved actual incoming edges. Similarity
            # never introduces an object outside this relation candidate set.
            stages.append("backlinks")
        else:
            stages.append("seeds")
        total_candidates = len(candidates)
        if (
            isinstance(request, SeedRefinement)
            and total_candidates > policy.candidate_limit
        ):
            raise SearchFailure(
                SearchFailureKind.SCOPE_REQUIRED,
                "Seed scope exceeds the candidate budget; narrow the scope",
            )
        candidates = candidates[: policy.candidate_limit]
        omitted = total_candidates - len(candidates)
        prepared = tuple(
            bound_evidence(candidate, query, policy.evidence_max_chars)
            for candidate in candidates
        )
        evaluated = 0
        if prepared and request.options.semantic is not SearchSemantic.NONE:
            if semantic is None:
                raise SearchFailure(
                    SearchFailureKind.INVALID_REQUEST,
                    "Semantic operation is not configured",
                )
            if (
                len(
                    json.dumps(
                        [item.to_json(rank=i + 1) for i, item in enumerate(prepared)],
                        ensure_ascii=False,
                    )
                )
                > policy.input_max_chars
            ):
                raise SearchFailure(
                    SearchFailureKind.SCOPE_REQUIRED,
                    "Candidate evidence exceeds the model input budget; narrow the scope",
                )
            try:
                ranked = await semantic(query, prepared, request.options.semantic)
            except SearchFailure as exc:
                if exc.kind is not SearchFailureKind.SELECTION_FAILED or isinstance(
                    request, SeedRefinement
                ):
                    raise
                missing.append(f"{request.options.semantic.value}:selection_failed")
            else:
                evaluated = len(prepared)
                prepared = ranked
                stages.append(request.options.semantic.value)
        selected = len(prepared)
        retained = prepared[: request.options.limit]
        coverage = SearchCoverage(
            scanned if scanned is not None else eligible,
            eligible,
            total_candidates,
            evaluated,
            selected,
            len(retained),
            omitted,
            source_complete,
            tuple(stages),
            tuple(missing),
        )
        return self.views.create(
            request, retained, coverage, page_max_chars=policy.page_max_chars
        )

    async def embedding_scores(
        self,
        query: str,
        candidates: tuple[SearchCandidate, ...],
        *,
        consumer: str,
        observer: ModelObserver | None,
    ) -> Mapping[str, float]:
        if self.embedding is None:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST, "No owner embedding binding"
            )
        # Independent evidence recall, including nested Skill resources. Unit
        # identities are local cache keys; output identities remain owner refs.
        documents = {
            f"{candidate.ref}\x1f{index}": evidence.text or candidate.title
            for candidate in candidates
            for index, evidence in enumerate(candidate.evidence)
        }
        scores = (
            await self.embedding.similarities(
                query, documents, consumer=consumer, observer=observer
            )
            if documents
            else {}
        )
        return {
            candidate.ref: max(
                scores[f"{candidate.ref}\x1f{index}"]
                for index in range(len(candidate.evidence))
            )
            for candidate in candidates
        }


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
            candidates.setdefault(candidate.ref, candidate)
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
                ("…" if start else "")
                + text[start : start + max(1, remaining - 2)]
                + "…"
            )
        evidence.append(SearchEvidence(item.ref, text, item.relation))
        remaining -= len(text)
    return replace(
        candidate,
        evidence=tuple(evidence),
        evidence_complete=candidate.evidence_complete
        and sum(len(item.text) for item in candidate.evidence) <= budget,
    )
