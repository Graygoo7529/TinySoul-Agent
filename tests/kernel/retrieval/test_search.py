from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from typing import cast

from tinysoul.infra.json import JsonObject
from tinysoul.infra.json.schema import JSONSchema
from tinysoul.infra.model_services.protocol import ModelFailureKind, ModelServiceError
from tinysoul.kernel.retrieval.contracts import (
    RetrievalRequest, QuerySource, DirectorySource, RefsSource, ResultSource,
    SourceKind, OperationKind, QueryChannel, TextQuery, ModelStep, FilterStep,
    SearchCandidate, SearchEvidence, SearchFailure, SearchFailureKind, CandidateSet,
)
from tinysoul.kernel.retrieval.engine import SearchEngine, SearchViews
from tinysoul.kernel.retrieval.operations import SearchCorpus, SearchSession
from tinysoul.kernel.retrieval.policy import RetrievalPolicy, retrieval_schema
from tinysoul.kernel.retrieval.requests import parse_retrieval_request


def candidate(identity, text, **attributes):
    return SearchCandidate(identity, identity, (SearchEvidence(identity + "#L1", text),), attributes)


class Vectors:
    def __init__(self):
        self.seen = {}
        self.failure = False

    async def similarities(self, query, documents, **kwargs):
        self.seen = dict(documents)
        if self.failure:
            raise ModelServiceError(ModelFailureKind.UNAVAILABLE, "unavailable")
        return {key: 0.9 if "automobile" in text else 0.1 for key, text in documents.items()}


def session(items, *, vectors=None, **changes):
    async def source(request):
        return SearchCorpus(items, request.source.query.text if isinstance(request.source, QuerySource) else "", len(items))
    policy = RetrievalPolicy("home.search", tuple(SourceKind), tuple(OperationKind), **changes)
    return SearchSession(action_id="home.search", retrieval_policies=(policy,), source=source, embedding=vectors)


async def test_independent_channels_retain_deep_semantic_hit_and_report_unavailable_channel():
    semantic = SearchCandidate("semantic", "Vehicle", (
        SearchEvidence("semantic#L1", "general introduction " * 150),
        SearchEvidence("semantic#L100", "automobile maintenance instructions"),
    ))
    vectors = Vectors()
    queries = session((candidate("lexical", "car"), semantic), vectors=vectors,
                      query_channels=(QueryChannel.LEXICAL, QueryChannel.EMBEDDING))
    request = RetrievalRequest(QuerySource("all", TextQuery("car")))
    page = await queries.search(request)
    assert {item.ref for item in page.items} == {"lexical", "semantic"}
    match = next(item for item in page.items if item.ref == "semantic")
    assert match.evidence[0].ref == "semantic#L100"
    assert "automobile" in match.evidence[0].text
    assert "embedding" in match.evidence[0].basis
    assert len(vectors.seen) == 3
    vectors.failure = True
    page = await queries.search(request)
    assert [item.ref for item in page.items] == ["lexical"]
    assert page.coverage.missing_stages == ("embedding:unavailable",)
    with pytest.raises(SearchFailure) as failure:
        await session((semantic,), vectors=vectors, query_channels=(QueryChannel.EMBEDDING,)).search(request)
    assert failure.value.kind is SearchFailureKind.SOURCE_UNAVAILABLE


async def test_pipeline_preserves_order_and_filter_can_reduce_model_input():
    items = (candidate("a", "A real document", kind="keep"),
             candidate("b", "B real document", kind="drop"),
             candidate("c", "C real document", kind="keep"))
    calls = []
    async def operation(step, candidates):
        calls.append((step.op, [item.ref for item in candidates]))
        assert all(item.content_units[0].text for item in candidates)
        return tuple(reversed(candidates)) if step.op is OperationKind.RERANK else candidates[:1]
    request = RetrievalRequest(DirectorySource("all"), (
        FilterStep({"kind": "keep"}),
        ModelStep(OperationKind.RERANK, "most useful"),
        ModelStep(OperationKind.SELECT, "resolve the question"),
    ))
    page = await SearchEngine(views=SearchViews()).compose(
        request, corpus=CandidateSet(items, 3), page_max_chars=8000,
        supported_filters=frozenset({"kind"}), apply_operation=operation,
    )
    assert calls == [(OperationKind.RERANK, ["a", "c"]), (OperationKind.SELECT, ["c", "a"])]
    assert [item.ref for item in page.items] == ["c"]
    assert page.coverage.final_count == 1
    assert page.items[0].evidence[0].text == "C real document"


async def test_refs_have_no_relevance_prefilter_and_explicit_failures_never_skip():
    items = (candidate("a", "unrelated wording"), candidate("b", "different vocabulary"))
    request = RetrievalRequest(RefsSource(("a", "b")), (ModelStep(OperationKind.SELECT, "cars"),))
    engine = SearchEngine(views=SearchViews())
    seen = []
    async def select(step, candidates):
        seen.extend(candidates)
        return ()
    page = await engine.compose(request, corpus=CandidateSet(items, 2),
                                page_max_chars=8000, apply_operation=select)
    assert len(seen) == 2 and page.items == ()
    async def failed(step, candidates):
        raise SearchFailure(SearchFailureKind.OPERATION_FAILED, "invalid model output")
    with pytest.raises(SearchFailure) as failure:
        await engine.compose(request, corpus=CandidateSet(items, 2),
                             page_max_chars=8000, apply_operation=failed)
    assert failure.value.kind is SearchFailureKind.OPERATION_FAILED
    assert failure.value.step == "select"
    async def cancelled(step, candidates):
        raise asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await engine.compose(request, corpus=CandidateSet(items, 2),
                             page_max_chars=8000, apply_operation=cancelled)


async def test_views_keep_all_members_and_original_content_for_result_source():
    calls = 0
    items = tuple(candidate(str(i), "long source " * 500, tags=["original"]) for i in range(5))
    async def source(request):
        nonlocal calls
        calls += 1
        return SearchCorpus(items, "", len(items))
    policy = RetrievalPolicy("home.search", tuple(SourceKind), tuple(OperationKind))
    queries = SearchSession(action_id="home.search", retrieval_policies=(policy,), source=source)
    page = await queries.search(RetrievalRequest(DirectorySource("all"), page_limit=1))
    assert len(page.items) == 1 and page.coverage.final_count == 5 and page.continuation
    result_ref, token = page.result_ref, page.continuation
    assert result_ref is not None
    page.items[0].attributes["tags"] = ["mutated"]
    result = await queries.search(RetrievalRequest(ResultSource(result_ref), page_limit=2))
    assert result.result_ref != result_ref
    assert result.items[0].attributes["tags"] == ["original"]
    assert result.coverage.final_count == 5 and calls == 1
    assert len(queries._engine.views.result(result_ref)[0].content_units[0].text) > len(page.items[0].evidence[0].text)
    assert await queries.search(token) == await queries.search(token)
    found = [*page.items]
    while page.continuation:
        page = await queries.search(page.continuation)
        found.extend(page.items)
    assert len(found) == 5
    queries.close()
    for request in (token, RetrievalRequest(ResultSource(result_ref))):
        with pytest.raises(SearchFailure) as failure:
            await queries.search(request)
        assert failure.value.kind is SearchFailureKind.VIEW_EXPIRED


def test_parser_and_schema_share_the_source_step_contract():
    policy = RetrievalPolicy("home.search", tuple(SourceKind), tuple(OperationKind), page_max_items=4)
    schema = JSONSchema(retrieval_schema({}, policy))
    value = {"source": {"kind": "refs", "refs": ["home:agent/test.md"]},
             "steps": [{"op": "select", "criterion": "useful"}]}
    schema.validate(cast(JsonObject, value))
    request = parse_retrieval_request(cast(JsonObject, value), policy)
    assert isinstance(request, RetrievalRequest) and request.page_limit == 4
    for invalid in (
        {**value, "model": "arbitrary"},
        {"source": {"kind": "refs", "refs": []}},
        {"source": {"kind": "directory", "scope": "all", "query": "hidden"}},
        {"continuation": "page", "steps": []},
        {**value, "page": {"limit": True}},
    ):
        with pytest.raises(SearchFailure):
            parse_retrieval_request(cast(JsonObject, invalid), policy)


async def test_filter_validation_and_snapshot_capacity_do_not_depend_on_result_count():
    async def unused(*args):
        raise AssertionError("No model is requested")
    engine = SearchEngine(views=SearchViews())
    request = RetrievalRequest(DirectorySource("all"), (FilterStep({"unknown": "value"}),))
    with pytest.raises(SearchFailure):
        await engine.compose(request, corpus=CandidateSet((), 0), page_max_chars=8000, apply_operation=unused)
    with pytest.raises(SearchFailure) as failure:
        await engine.compose(RetrievalRequest(DirectorySource("all")),
            corpus=CandidateSet((candidate("a", "large " * 100),), 1),
            page_max_chars=8000, snapshot_max_chars=100, apply_operation=unused)
    assert failure.value.kind is SearchFailureKind.SCOPE_REQUIRED
