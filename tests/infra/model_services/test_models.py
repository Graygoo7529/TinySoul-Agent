from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from tinysoul.infra.config import ConfigError
from tinysoul.infra.json import to_json_object
from tinysoul.infra.model_services.config import (
    ModelAdapter,
    ModelCapability,
    ModelServicesSettings,
    ServiceModel,
    ServiceProvider,
    ServiceProviderBinding,
    ServiceUse,
    parse_model_services,
)
from tinysoul.infra.model_services.protocol import (
    DecisionQuestion,
    DecisionRequest,
    ModelFailureKind,
    ModelServiceError,
    QuestionKind,
    parse_decision_response,
)
from tinysoul.infra.model_services.service import ModelServices, ModelCallStatus
from tinysoul.infra.model_services.vectors import EmbeddingIndex
from tinysoul.infra.settings import parse_infra_settings


def settings(kind=ModelCapability.EMBEDDING, *, routes=2):
    adapter = (
        ModelAdapter.OPENAI_EMBEDDING
        if kind is ModelCapability.EMBEDDING
        else ModelAdapter.TYPESAFE_SYSTEM_ONE
    )
    providers = tuple(
        ServiceProvider(
            f"p{i}", adapter, f"https://p{i}.example/v1", "TEST_KEY", max_retries=0
        )
        for i in range(routes)
    )
    return ModelServicesSettings(
        providers,
        (
            ServiceModel(
                "model",
                kind,
                tuple(ServiceProviderBinding(p.id, "real-model") for p in providers),
                dimensions=2 if kind is ModelCapability.EMBEDDING else None,
            ),
        ),
        (ServiceUse("use", kind, "model"),),
    )


def test_directory_validates_structure_without_connecting_unselected_models():
    config = settings()
    with pytest.raises(ConfigError, match="credential"):
        config.resolve("use", ModelCapability.EMBEDDING, {})
    _, routes = config.resolve("use", ModelCapability.EMBEDDING, {"TEST_KEY": "secret"})
    assert [provider.id for provider, _ in routes] == ["p0", "p1"]
    with pytest.raises(ConfigError, match="capability"):
        config.resolve(
            "use", ModelCapability.STRUCTURED_DECISION, {"TEST_KEY": "secret"}
        )
    with pytest.raises(ConfigError):
        replace(config, uses=(ServiceUse("bad", ModelCapability.EMBEDDING, "missing"),))
    with pytest.raises(ConfigError):
        parse_model_services({"providers": [{"api_key": "secret"}]})
    with pytest.raises(ConfigError):
        parse_infra_settings({"embedding": {"enabled": True}})


def mixed_request():
    return DecisionRequest(
        {"text": "sample"},
        (
            DecisionQuestion("yes", QuestionKind.NOUL, "Is this a sample?"),
            DecisionQuestion(
                "which",
                QuestionKind.CHOICE,
                "Pick a category",
                choices=(("a", "one"), ("b", "two")),
            ),
            DecisionQuestion(
                "quality",
                QuestionKind.SCORE,
                "Rate relevance",
                levels=("none", "background", "supports", "direct"),
            ),
        ),
    )


def mixed_response():
    return to_json_object(
        {
            "model": "jev-test",
            "answers": {
                "yes": {"type": "noul", "noul": 0.9},
                "which": {
                    "type": "choice",
                    "choice": "a",
                    "probabilities": {"a": 0.8, "b": 0.2},
                    "confidence": 0.6,
                },
                "quality": {
                    "type": "score",
                    "score": 2.5,
                    "legend": {
                        "0": "none",
                        "1": "background",
                        "2": "supports",
                        "3": "direct",
                    },
                    "probabilities": {"0": 0, "1": 0, "2": 0.5, "3": 0.5},
                    "confidence": 0.3,
                },
            },
            "usage": {"input_tokens": 20, "output_tokens": 8},
        }
    )


def test_decision_protocol_keeps_fractional_scores_and_exact_question_mapping():
    result = parse_decision_response(mixed_response(), mixed_request())
    assert [answer.value for answer in result.answers] == [0.9, "a", 2.5]
    assert result.input_tokens == 20
    for change in ("unknown", "type", "range", "distribution"):
        value = mixed_response()
        answers = value["answers"]
        assert isinstance(answers, dict)
        if change == "unknown":
            answers["missing"] = answers.pop("yes")
        else:
            answer = answers["quality"]
            assert isinstance(answer, dict)
            answer[
                {"type": "type", "range": "score", "distribution": "probabilities"}[
                    change
                ]
            ] = {"type": "choice", "range": 4, "distribution": {"0": 1}}[change]
        with pytest.raises(ModelServiceError):
            parse_decision_response(value, mixed_request())


async def test_provider_fallback_and_observation_are_bounded_and_secret_free():
    calls = []

    def respond(request):
        calls.append(request.url.host)
        return (
            httpx.Response(503)
            if request.url.host == "p0.example"
            else httpx.Response(200, json=mixed_response())
        )

    events = []
    services = ModelServices(
        settings(ModelCapability.STRUCTURED_DECISION),
        env={"TEST_KEY": "secret"},
        transport=httpx.MockTransport(respond),
    )
    try:
        result = await services.decide(
            "use", mixed_request(), consumer="test.select", observer=events.append
        )
        assert result.answers[2].value == 2.5
        assert calls == ["p0.example", "p1.example"]
        assert len({event.call_id for event in events}) == 1
        assert [event.status for event in events] == [
            ModelCallStatus.STARTED,
            ModelCallStatus.FAILED,
            ModelCallStatus.STARTED,
            ModelCallStatus.COMPLETED,
        ]
        assert events[-1].attempt == 2 and events[-1].input_tokens == 20
        assert "secret" not in repr(events)

        def broken_sink(event):
            raise RuntimeError("observer failure")

        assert await services.decide(
            "use", mixed_request(), consumer="test.select", observer=broken_sink
        )
    finally:
        await services.close()


@pytest.mark.parametrize(
    "status, kind",
    [
        (401, ModelFailureKind.AUTHENTICATION),
        (400, ModelFailureKind.CONTRACT),
        (413, ModelFailureKind.CAPACITY),
    ],
)
async def test_nonrecoverable_http_failures_do_not_switch_provider(status, kind):
    calls = []

    def respond(request):
        calls.append(request.url.host)
        return httpx.Response(status, text="private provider detail")

    services = ModelServices(
        settings(ModelCapability.STRUCTURED_DECISION),
        env={"TEST_KEY": "secret"},
        transport=httpx.MockTransport(respond),
    )
    try:
        with pytest.raises(ModelServiceError) as failed:
            await services.decide("use", mixed_request(), consumer="test.select")
        assert failed.value.kind is kind
        assert "private" not in str(failed.value)
        assert calls == ["p0.example"]
    finally:
        await services.close()


async def test_embedding_fallback_restarts_document_and_query_vectors_and_rebuilds_cache(
    tmp_path: Path,
):
    calls = []

    def respond(request):
        body = json.loads(request.content)
        texts = body["input"]
        calls.append((request.url.host, tuple(texts)))
        if request.url.host == "p0.example" and texts == ["query"]:
            return httpx.Response(503)
        # Provider 0 and provider 1 use opposing coordinate systems.
        flip = request.url.host == "p1.example"
        data = []
        for i, text in reversed(list(enumerate(texts))):
            same = text in {"relevant", "query"}
            vector = [0, 1] if same == flip else [1, 0]
            data.append({"index": i, "embedding": vector})
        return httpx.Response(200, json={"data": data})

    services = ModelServices(
        settings(), env={"TEST_KEY": "secret"}, transport=httpx.MockTransport(respond)
    )
    index = EmbeddingIndex(path=tmp_path / "cache", services=services, use="use")
    try:
        documents = {"a": "relevant", "b": "unrelated"}
        scores = await index.similarities(
            "query", documents, consumer="home.search.discovery"
        )
        assert scores == {"a": 1.0, "b": 0.0}
        assert calls == [
            ("p0.example", ("relevant", "unrelated")),
            ("p0.example", ("query",)),
            ("p1.example", ("relevant", "unrelated")),
            ("p1.example", ("query",)),
        ]
        cache = next((tmp_path / "cache").glob("*.json"))
        calls.clear()
        await index.similarities("query", documents)
        assert ("p1.example", ("relevant", "unrelated")) not in calls
        cache.write_text("broken", encoding="utf-8")
        calls.clear()
        assert await index.similarities("query", documents) == scores
        assert ("p1.example", ("relevant", "unrelated")) in calls
    finally:
        await services.close()


async def test_cancellation_never_switches_provider_and_shared_client_closes_once():
    started = asyncio.Event()
    calls = []

    class Transport(httpx.AsyncBaseTransport):
        closes = 0

        async def handle_async_request(self, request):
            calls.append(request.url.host)
            started.set()
            await asyncio.Event().wait()
            return httpx.Response(200)

        async def aclose(self):
            self.closes += 1

    transport = Transport()
    services = ModelServices(
        settings(), env={"TEST_KEY": "secret"}, transport=transport
    )
    session = services.embedding_sessions("use")[0]
    events = []
    task = asyncio.create_task(
        session.embed(("text",), consumer="test", observer=events.append)
    )
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls == ["p0.example"]
    assert events[-1].status is ModelCallStatus.CANCELLED
    await services.close()
    await services.close()
    assert transport.closes == 1
    with pytest.raises(ModelServiceError):
        services.embedding_sessions("use")

async def test_vector_cache_merges_disjoint_scopes_and_reuses_text_across_candidate_ids(tmp_path: Path):
    calls = []
    def respond(request):
        texts = json.loads(request.content)["input"]
        calls.append(tuple(texts))
        return httpx.Response(200, json={"data": [
            {"index": index, "embedding": [1, 0]} for index, _ in enumerate(texts)
        ]})
    services = ModelServices(settings(routes=1), env={"TEST_KEY": "secret"},
                             transport=httpx.MockTransport(respond))
    try:
        index = EmbeddingIndex(path=tmp_path / "cache", services=services, use="use")
        await index.similarities("q", {"a": "first content"})
        await index.similarities("q", {"b": "second content"})
        calls.clear()
        await index.similarities("q", {"new-id": "first content", "b": "second content"})
        assert calls == [("q",)]
        # A different extraction scheme is a different content representation.
        other = EmbeddingIndex(path=tmp_path / "cache", services=services, use="use", extraction="other")
        calls.clear()
        await other.similarities("q", {"a": "first content"})
        assert calls == [("first content",), ("q",)]
    finally:
        await services.close()
