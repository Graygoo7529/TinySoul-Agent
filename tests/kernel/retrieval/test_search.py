from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from tinysoul.infra.config import ConfigError
from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.loop.lifecycle.preparation import TurnPreparationRequest
from tinysoul.runtime import RunScope
from tinysoul.infra.json import JsonObject
from tinysoul.infra.json.schema import JSONSchema
from tinysoul.infra.model_services.protocol import ModelFailureKind, ModelServiceError
from tinysoul.kernel.retrieval.contracts import (
    BacklinkSearch,
    CandidateSource,
    QueryDiscovery,
    SearchCandidate,
    SearchContext,
    SearchEvidence,
    SearchFailure,
    SearchFailureKind,
    SearchMode,
    SearchOptions,
    SearchSemantic,
    SeedRefinement,
    TextQuery,
)
from tinysoul.kernel.retrieval.engine import SearchEngine, SearchViews
from tinysoul.kernel.retrieval.operations import SearchCorpus, SearchSession
from tinysoul.kernel.retrieval.policy import (
    SearchCapability,
    SearchPolicy,
    search_schema,
    validate_search_policies,
)
from tinysoul.kernel.retrieval.requests import eligible, parse_search_request


def candidate(identity: str, text: str) -> SearchCandidate:
    return SearchCandidate(
        identity,
        identity,
        (SearchEvidence(identity + "#L1", text),),
        {"tags": ["sample"]},
    )


class Vectors:
    def __init__(self, failure=False):
        self.seen = {}
        self.failure = failure

    async def similarities(self, query, documents, **kwargs):
        self.seen = dict(documents)
        if self.failure:
            raise ModelServiceError(
                ModelFailureKind.UNAVAILABLE, "temporarily unavailable"
            )
        return {
            key: 0.9 if "automobile" in text else 0.1 for key, text in documents.items()
        }


async def test_independent_vector_recall_and_visible_source_failure():
    items = (candidate("lexical", "car"), candidate("semantic", "automobile"))
    vectors = Vectors()
    engine = SearchEngine(views=SearchViews(), embedding=vectors)
    policy = SearchPolicy(
        "home.search",
        SearchMode.QUERY_DISCOVERY,
        (CandidateSource.LEXICAL, CandidateSource.EMBEDDING),
    )
    request = QueryDiscovery(TextQuery("car"), SearchOptions("all"))
    page = await engine.search(request, policy=policy, candidates=items, query="car")
    assert {item.ref for item in page.items} == {"lexical", "semantic"}
    assert len(vectors.seen) == 2
    assert page.coverage.stages == ("lexical", "embedding")
    vectors.failure = True
    page = await engine.search(request, policy=policy, candidates=items, query="car")
    assert [item.ref for item in page.items] == ["lexical"]
    assert page.coverage.missing_stages == ("embedding:unavailable",)
    with pytest.raises(SearchFailure) as failure:
        await engine.search(
            request,
            policy=replace(policy, candidate_sources=(CandidateSource.EMBEDDING,)),
            candidates=items,
            query="car",
        )
    assert failure.value.kind is SearchFailureKind.SOURCE_UNAVAILABLE


async def test_seed_has_no_relevance_prefilter_and_selection_can_be_empty():
    items = (candidate("a", "not a lexical match"), candidate("b", "another topic"))
    policy = SearchPolicy(
        "home.search",
        SearchMode.SEED_REFINEMENT,
        default_semantic=SearchSemantic.SELECT,
        allowed_semantic=(SearchSemantic.SELECT,),
    )
    request = SeedRefinement(
        "汽车", SearchOptions("all", semantic=SearchSemantic.SELECT), ("a", "b")
    )
    seen = []

    async def select(query, candidates, operation):
        seen.extend(candidates)
        return ()

    engine = SearchEngine(views=SearchViews())
    page = await engine.search(
        request, policy=policy, candidates=items, query="汽车", semantic=select
    )
    assert {item.ref for item in seen} == {"a", "b"}
    assert page.items == () and page.coverage.evaluated == 2
    with pytest.raises(SearchFailure) as failure:
        await engine.search(
            request,
            policy=replace(policy, candidate_limit=1),
            candidates=items,
            query="汽车",
            semantic=select,
        )
    assert failure.value.kind is SearchFailureKind.SCOPE_REQUIRED


async def test_optional_rank_failure_keeps_candidates_required_select_and_cancel_propagate():
    items = (candidate("a", "car"),)
    policy = SearchPolicy(
        "home.search",
        SearchMode.QUERY_DISCOVERY,
        (CandidateSource.LEXICAL,),
        SearchSemantic.RANK,
        (SearchSemantic.RANK,),
    )
    request = QueryDiscovery(
        TextQuery("car"), SearchOptions("all", semantic=SearchSemantic.RANK)
    )

    async def failed(*args):
        raise SearchFailure(SearchFailureKind.SELECTION_FAILED, "invalid output")

    engine = SearchEngine(views=SearchViews())
    page = await engine.search(
        request, policy=policy, candidates=items, query="car", semantic=failed
    )
    assert page.items[0].ref == "a" and page.coverage.missing_stages == (
        "rank:selection_failed",
    )
    seed_policy = replace(
        policy,
        mode=SearchMode.SEED_REFINEMENT,
        candidate_sources=(),
        default_semantic=SearchSemantic.SELECT,
        allowed_semantic=(SearchSemantic.SELECT,),
    )
    seed = SeedRefinement(
        "car", SearchOptions("all", semantic=SearchSemantic.SELECT), ("a",)
    )
    with pytest.raises(SearchFailure):
        await engine.search(
            seed, policy=seed_policy, candidates=items, query="car", semantic=failed
        )

    async def cancelled(*args):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await engine.search(
            request, policy=policy, candidates=items, query="car", semantic=cancelled
        )


async def test_search_pages_are_snapshots_and_expire_with_query_scope():
    calls = 0
    items = tuple(candidate(str(i), "fact " * 180) for i in range(5))

    async def source(request):
        nonlocal calls
        calls += 1
        return SearchCorpus(items, "fact", len(items))

    policy = SearchPolicy(
        "home.search",
        SearchMode.QUERY_DISCOVERY,
        (CandidateSource.LEXICAL,),
        page_max_chars=2400,
        evidence_max_chars=900,
    )
    session = SearchSession(action_id="home.search", policies=(policy,), source=source)
    page = await session.search(QueryDiscovery(TextQuery("fact"), SearchOptions("all")))
    assert page.continuation
    page.items[0].attributes["tags"] = ["mutated by caller"]
    first_token = page.continuation
    following = await session.search(first_token)
    assert following == await session.search(first_token)
    found = [*page.items]
    while page.continuation:
        page = await session.search(page.continuation)
        found.extend(page.items)
    assert len(found) == len(items) and calls == 1
    assert items[0].attributes["tags"] == ["sample"]
    other = SearchSession(action_id="home.search", policies=(policy,), source=source)
    with pytest.raises(SearchFailure):
        await other.search(first_token)
    await session.close_turn("turn")
    with pytest.raises(SearchFailure) as failure:
        await session.search(first_token)
    assert failure.value.kind is SearchFailureKind.CONTINUATION_EXPIRED
    await session.prepare(
        TurnPreparationRequest(
            "next", "new query", CalendarDay.parse("2026-09-26"), RunScope()
        )
    )
    with pytest.raises(SearchFailure):
        await session.search(first_token)
    assert (
        await session.search(QueryDiscovery(TextQuery("fact"), SearchOptions("all")))
    ).items


def test_policy_schema_and_request_normalization_share_finite_choices():
    policy = SearchPolicy(
        "home.search",
        SearchMode.SEED_REFINEMENT,
        default_semantic=SearchSemantic.SELECT,
        allowed_semantic=(SearchSemantic.SELECT,),
        default_context=SearchContext.CURRENT,
        allowed_context=(SearchContext.CURRENT, SearchContext.NONE),
    )
    schema = JSONSchema(
        search_schema({"properties": {}}, (policy,), action_id="home.search")
    )
    value: JsonObject = {
        "mode": "seed_refinement",
        "query": "car",
        "scope": "all",
        "seed_refs": ["home:agent/a.md"],
    }
    schema.validate(value)
    request = parse_search_request(value, (policy,))
    assert isinstance(request, SeedRefinement)
    assert request.options.context is SearchContext.CURRENT
    with pytest.raises(SearchFailure):
        parse_search_request({**value, "semantic": "none"}, (policy,))
    with pytest.raises(SearchFailure):
        BacklinkSearch(
            "home:agent/a.md", SearchOptions("all", semantic=SearchSemantic.RANK)
        )
    with pytest.raises(ConfigError):
        replace(policy, allowed_semantic=(SearchSemantic.NONE,))
    with pytest.raises(SearchFailure):
        eligible({"tag": "a"}, {"unknown": "b"}, supported=frozenset({"tag"}))
    capability = SearchCapability("home.search", (SearchMode.SEED_REFINEMENT,))
    validate_search_policies((capability,), (policy,))
    with pytest.raises(ConfigError):
        validate_search_policies(
            (capability,), (replace(policy, action_id="core.answer"),)
        )
    with pytest.raises(ConfigError):
        validate_search_policies(
            (capability,), (replace(policy, mode=SearchMode.BACKLINK_SEARCH),)
        )
