from __future__ import annotations

import asyncio
import json
import os
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from tinysoul.infra.json import JsonObject, to_json_value
from tinysoul.infra.model_services import ModelServices
from tinysoul.infra.model_services.config import (
    ModelAdapter,
    ModelCapability,
    ModelServicesSettings,
    ServiceModel,
    ServiceProvider,
    ServiceProviderBinding,
    ServiceUse,
)
from tinysoul.kernel.action.models import (
    ModelImplementation,
    ModelOperation,
    ModelUseBinding,
    ModelUseDescriptor,
    ModelUseRegistry,
)
from tinysoul.kernel.retrieval.contracts import (
    ContentCoverage,
    ContentUnit,
    EvidenceKind,
    OperationKind,
    SearchCandidate,
    SearchFailure,
    SearchFailureKind,
)
from tinysoul.kernel.retrieval.selection import CandidateSelector
from tinysoul.llm.protocol.cache import PromptCache, PromptCacheBreakpoint
from tinysoul.llm.protocol.messages import MessageStack, UserMessage
from tinysoul.llm.protocol.responses import JsonAnswer, RawResponse, TaskResult

SAMPLES = (
    (
        "home.search",
        "如何检查 CSV 缺失值？",
        (
            (
                "home:top/skills/data",
                "数据检查",
                "用 pandas isna 检查 CSV 中的缺失值并统计每列缺失比例。",
            ),
            ("home:top/skills/cooking", "晚餐", "番茄炒蛋的配料和做法。"),
        ),
    ),
    (
        "memory.search",
        "Which datastore did we select for durable relational records?",
        (
            (
                "memory:fact/database",
                "Database decision",
                "We selected PostgreSQL for durable relational records and transactional queries.",
            ),
            ("memory:fact/holiday", "Holiday", "The summer vacation is in July."),
        ),
    ),
    (
        "expand.search",
        "Add two integers",
        (
            (
                "mcp:math/add",
                "add",
                "Add integer parameters a and b and return their sum.",
            ),
            (
                "mcp:weather/forecast",
                "forecast",
                "Return a weather forecast for a city.",
            ),
        ),
    ),
)


def candidates(rows):
    return tuple(
        SearchCandidate(ref, title, (ContentUnit(ref, ref, text),))
        for ref, title, text in rows
    )


def registry(action, implementation):
    return ModelUseRegistry(
        tuple(
            ModelUseDescriptor(
                f"{action}.{operation.value}", action, operation, (implementation,)
            )
            for operation in (ModelOperation.SELECT, ModelOperation.RERANK)
        ),
        tuple(
            ModelUseBinding(
                f"{action}.{operation.value}",
                implementation,
                task_profile="selector"
                if implementation is ModelImplementation.LLM_TASK
                else None,
                use="decision"
                if implementation is ModelImplementation.DECISION
                else None,
            )
            for operation in (ModelOperation.SELECT, ModelOperation.RERANK)
        ),
    )


def decision_settings():
    return ModelServicesSettings(
        (
            ServiceProvider(
                "typesafe",
                ModelAdapter.TYPESAFE_SYSTEM_ONE,
                "https://api.typesafe.ai/v1",
                "TYPESAFE_API_KEY",
                max_retries=0,
            ),
        ),
        (
            ServiceModel(
                "decision",
                ModelCapability.DECISION,
                (ServiceProviderBinding("typesafe", "decision-latest"),),
            ),
        ),
        (ServiceUse("decision", ModelCapability.DECISION, "decision"),),
    )


async def unused_invoke(call):
    raise AssertionError("A decision model binding must not invoke LLM")


async def test_repeated_model_steps_link_search_observations_to_distinct_tasks():
    from tinysoul.kernel.retrieval.contracts import (
        DirectorySource,
        ModelStep,
        RetrievalRequest,
        SearchContext,
        SourceKind,
    )
    from tinysoul.kernel.retrieval.operations import (
        SearchCorpus,
        SearchSession,
        SelectionInput,
    )
    from tinysoul.kernel.retrieval.policy import RetrievalOperationPolicy, RetrievalPolicy
    from tinysoul.runtime import ObservationEvent, ObservationLevel

    class Observations:
        def __init__(self):
            self.events: list[ObservationEvent] = []

        def enabled(self, level: ObservationLevel) -> bool:
            return True

        def emit(self, event: ObservationEvent) -> None:
            self.events.append(event)

    calls = []

    async def invoke(call):
        calls.append(call)
        return TaskResult.success(
            raw_response=RawResponse("{}", "model", "provider"),
            answer=JsonAnswer({"items": [{"id": "c0", "basis_ids": ["u0"]}]}),
            tool_calls=(),
        )

    async def source(request):
        return SearchCorpus(candidates(SAMPLES[0][2][:1]), "", 1)

    observations = Observations()
    services = ModelServices(ModelServicesSettings(), env={})
    session = SearchSession(
        action_id="home.search",
        retrieval_policies=(
            RetrievalPolicy(
                "home.search",
                tuple(SourceKind),
                tuple(OperationKind),
                operation_policies=(
                    RetrievalOperationPolicy(OperationKind.RERANK, tuple(SearchContext)),
                ),
            ),
        ),
        source=source,
        selector=CandidateSelector(
            models=registry("home.search", ModelImplementation.LLM_TASK),
            invoke=invoke,
            services=services,
        ),
        observations=observations,
    )
    cache = PromptCache(
        key="2026-10-22/1",
        breakpoints=(PromptCacheBreakpoint("background", 0),),
    )
    context = MessageStack.of(UserMessage.from_text("Shared context"))
    page = await session.search(
        RetrievalRequest(
            DirectorySource("all"),
            (
                ModelStep(
                    OperationKind.RERANK,
                    "first criterion",
                    context=SearchContext.CURRENT,
                ),
                ModelStep(OperationKind.RERANK, "new criterion"),
            ),
        ),
        inputs=SelectionInput(context=context, prompt_cache=cache),
    )
    assert calls[0].prompt_cache == cache
    assert calls[0].messages.messages[0] == context.messages[0]
    assert calls[1].prompt_cache == PromptCache(key=cache.key)
    assert context.messages[0] not in calls[1].messages.messages
    invoked = [
        event.payload
        for event in observations.events
        if event.name == "retrieval.model.invoked"
    ]
    completed = [
        event.payload
        for event in observations.events
        if event.name == "retrieval.step.completed"
    ]
    assert [item["step_index"] for item in invoked] == [0, 1]
    assert [item["task_id"] for item in invoked] == [call.task_id for call in calls]
    assert len({item["task_id"] for item in invoked}) == 2
    assert len({item["search_id"] for item in (*invoked, *completed)}) == 1
    assert [item["step_index"] for item in completed] == [0, 1]
    evaluation = page.items[0].candidate.evaluation
    assert evaluation is not None and evaluation.step_index == 1
    await services.close()


async def test_llm_selection_accepts_only_known_unique_subset_and_rank_requires_permutation():
    action, query, rows = SAMPLES[0]
    answer: JsonObject = {
        "items": [{"id": "c1", "basis_ids": []}, {"id": "c0", "basis_ids": ["u0"]}]
    }
    calls = []

    async def invoke(call):
        calls.append(call)
        return TaskResult.success(
            raw_response=RawResponse("{}", "model", "provider"),
            answer=JsonAnswer(answer),
            tool_calls=(),
        )

    services = ModelServices(ModelServicesSettings(), env={})
    selector = CandidateSelector(
        models=registry(action, ModelImplementation.LLM_TASK),
        invoke=invoke,
        services=services,
    )
    ranked = await selector.apply(
        consumer=f"{action}.rerank",
        query=query,
        candidates=candidates(rows),
        operation=OperationKind.RERANK,
    )
    assert [item.ref for item in ranked] == [rows[1][0], rows[0][0]]
    assert calls[0].consumer == f"{action}.rerank"
    for invalid in (["c0"], ["c0", "c0"], ["unknown"]):
        answer["items"] = to_json_value(
            [{"id": key, "basis_ids": []} for key in invalid]
        )
        with pytest.raises(SearchFailure):
            await selector.apply(
                consumer=f"{action}.rerank",
                query=query,
                candidates=candidates(rows),
                operation=OperationKind.RERANK,
            )
    answer["items"] = []
    assert (
        await selector.apply(
            consumer=f"{action}.select",
            query=query,
            candidates=candidates(rows),
            operation=OperationKind.SELECT,
        )
        == ()
    )
    with pytest.raises(SearchFailure) as failure:
        await selector.apply(
            consumer=f"{action}.select",
            query=query,
            candidates=candidates(rows),
            operation=OperationKind.SELECT,
            max_input_chars=1,
        )
    assert failure.value.kind is SearchFailureKind.SCOPE_REQUIRED
    await services.close()


async def test_llm_basis_can_only_reference_actual_input_and_preserves_snapshot():
    item = SearchCandidate(
        "home:top/skills/test",
        "Test",
        (ContentUnit("body", "home:resource/skills/test/deep.md", "visible " * 1000),),
    )
    answer: JsonObject = {"items": [{"id": "c0", "basis_ids": ["u0"]}]}
    calls = []

    async def invoke(call):
        calls.append(call)
        return TaskResult.success(
            raw_response=RawResponse("{}", "model", "provider"),
            answer=JsonAnswer(answer),
            tool_calls=(),
        )

    services = ModelServices(ModelServicesSettings(), env={})
    selector = CandidateSelector(
        models=registry("home.search", ModelImplementation.LLM_TASK),
        invoke=invoke,
        services=services,
    )

    async def select():
        return await selector.apply(
            consumer="home.search.select",
            operation=OperationKind.SELECT,
            query="find relevant material",
            candidates=(item,),
        )

    selected = await select()
    assert len(calls) == 1 and selected[0].content_units == item.content_units
    evaluation = selected[0].evaluation
    assert evaluation and evaluation.input_coverage is ContentCoverage.EXCERPT
    assert (
        evaluation.basis[0].kind is EvidenceKind.MODEL
            and evaluation.basis[0].end == 4096
    )
    answer["items"] = [{"id": "c0", "basis_ids": ["body"]}]
    with pytest.raises(SearchFailure) as failure:
        await select()
    assert failure.value.kind is SearchFailureKind.OPERATION_FAILED
    answer["items"] = [{"id": "c0", "basis_ids": []}]
    selected = await select()
    assert selected[0].evaluation and not selected[0].evaluation.basis
    await services.close()


async def test_embedding_step_retains_its_contribution_and_actual_full_input():
    from tests.kernel.retrieval.test_search import Vectors

    models = ModelUseRegistry(
        (
            ModelUseDescriptor(
                "home.search.rerank",
                "home.search",
                ModelOperation.RERANK,
                (ModelImplementation.EMBEDDING_SIMILARITY,),
                embedding_owner="home",
            ),
        ),
        (
            ModelUseBinding(
                "home.search.rerank", ModelImplementation.EMBEDDING_SIMILARITY
            ),
        ),
    )
    services = ModelServices(ModelServicesSettings(), env={})
    item = SearchCandidate(
        "home:top/skills/test",
        "Test",
        (
            ContentUnit("intro", "intro", "introduction " * 400),
            ContentUnit("hit", "deep", "automobile instructions"),
        ),
    )
    selector = CandidateSelector(models=models, invoke=unused_invoke, services=services)
    result = await selector.apply(
        consumer="home.search.rerank",
        operation=OperationKind.RERANK,
        query="car",
        candidates=(item,),
        embedding=Vectors(),
    )
    evaluation = result[0].evaluation
    assert evaluation and evaluation.input_coverage is ContentCoverage.FULL
    assert evaluation.basis[0].unit_id == "hit" and evaluation.score == 0.9
    from tinysoul.kernel.retrieval.disclosure import project_candidate

    assert "automobile" in project_candidate(result[0], 1000).fragments[0].text
    await services.close()


@pytest.mark.parametrize("action,query,rows", SAMPLES)
async def test_decision_uses_candidate_specific_questions_and_preserves_rank_membership(
    action, query, rows
):
    def respond(request):
        body = json.loads(request.content)
        assert [item["ref"] for item in body["state"]["candidates"]] == [
            row[0] for row in rows
        ]
        assert "candidates[0]" in body["questions"]["c0"]["instructions"]
        answers = {}
        for identity, question in body["questions"].items():
            score = 3 if identity == "c0" else 0
            answers[identity] = {
                "type": "score",
                "score": score,
                "legend": {
                    str(i): label for i, label in enumerate(question["criteria"])
                },
                "probabilities": {str(i): int(i == score) for i in range(4)},
                "confidence": 1,
            }
        return httpx.Response(200, json={"model": "decision-test", "answers": answers})

    services = ModelServices(
        decision_settings(),
        env={"TYPESAFE_API_KEY": "test"},
        transport=httpx.MockTransport(respond),
    )
    selector = CandidateSelector(
        models=registry(action, ModelImplementation.DECISION),
        invoke=unused_invoke,
        services=services,
    )
    selected = await selector.apply(
        consumer=f"{action}.select",
        query=query,
        candidates=candidates(rows),
        operation=OperationKind.SELECT,
    )
    assert [item.ref for item in selected] == [rows[0][0]]
    ranked = await selector.apply(
        consumer=f"{action}.rerank",
        query=query,
        candidates=candidates(rows),
        operation=OperationKind.RERANK,
    )
    assert {item.ref for item in ranked} == {row[0] for row in rows}
    await services.close()


@pytest.mark.external
@pytest.mark.skipif(
    os.environ.get("TINYSOUL_EXTERNAL_DECISION") != "1"
    or not os.environ.get("TYPESAFE_API_KEY"),
    reason="Explicit decision model external switch and credential required",
)
async def test_real_decision_representative_retrieval_quality():
    services = ModelServices(decision_settings(), env=os.environ)
    try:
        for action, query, rows in SAMPLES:
            selector = CandidateSelector(
                models=registry(action, ModelImplementation.DECISION),
                invoke=unused_invoke,
                services=services,
            )
            selected = await selector.apply(
                consumer=f"{action}.select",
                query=query,
                candidates=candidates(rows),
                operation=OperationKind.SELECT,
            )
            assert [item.ref for item in selected] == [rows[0][0]]
            ranked = await selector.apply(
                consumer=f"{action}.rerank",
                query=query,
                candidates=candidates(rows),
                operation=OperationKind.RERANK,
            )
            assert [item.ref for item in ranked] == [row[0] for row in rows]
            unrelated = await selector.apply(
                consumer=f"{action}.select",
                query="Explain the spectrum of a distant pulsar.",
                candidates=candidates(rows),
                operation=OperationKind.SELECT,
            )
            assert unrelated == ()
    finally:
        await services.close()


@pytest.mark.external
@pytest.mark.skipif(
    os.environ.get("TINYSOUL_EXTERNAL_RETRIEVAL_LLM") != "1",
    reason="Explicit LLM quality switch required",
)
async def test_real_llm_representative_retrieval_quality(tmp_path: Path):
    from tinysoul.gateway.project.initializer import ProjectInitializer
    from tinysoul.infra.config import ConfigEnvironment
    from tinysoul.infra.config.sources.dotenv import DotenvSource
    from tinysoul.llm.config.loader import LLMConfigParser
    from tinysoul.llm.execution.model_chain import TaskSpecTable
    from tinysoul.llm.execution.registry import ModelRegistry
    from tinysoul.llm.execution.task import LLMTaskRunner
    from tinysoul.llm.protocol.routing import ModelChain, RetryPolicy, TaskSpec
    from tinysoul.llm.adapter.factory import build_provider_registry

    root = tmp_path / "project"
    ProjectInitializer().initialize(root)
    credentials = os.environ.get("TINYSOUL_TEST_CREDENTIAL_FILE")
    env = {
        **(DotenvSource(Path(credentials)).load_raw() if credentials else {}),
        **os.environ,
    }
    environment = ConfigEnvironment.from_project_root(root, env=env)
    config = LLMConfigParser().parse(environment.section_tree("llm"))
    model = config.models.get(
        os.environ.get("TINYSOUL_RETRIEVAL_MODEL", "deepseek-flash")
    )
    provider_id = os.environ.get("TINYSOUL_RETRIEVAL_PROVIDER", "deepseek")
    binding = next(item for item in model.providers if item.provider_id == provider_id)
    provider = replace(config.provider(binding.provider_id), enabled=True)
    assert provider.configured_api_key(env), "The selected provider needs a credential"
    providers = await build_provider_registry((provider,), models=ModelRegistry([replace(model, providers=(binding,))]), env=env)
    runner = LLMTaskRunner(
        models=ModelRegistry([replace(model, providers=(binding,))]),
        providers=providers,
        tasks=TaskSpecTable(
            [
                TaskSpec(
                    "selector",
                    ModelChain(
                        "selector",
                        (model.id,),
                        RetryPolicy(max_retries_per_provider=0, max_cycles=1),
                    ),
                )
            ]
        ),
    )
    services = ModelServices(ModelServicesSettings(), env={})
    try:
        for action, query, rows in SAMPLES:
            selector = CandidateSelector(
                models=registry(action, ModelImplementation.LLM_TASK),
                invoke=runner.invoke,
                services=services,
            )
            selected, ranked, unrelated = await asyncio.gather(
                selector.apply(
                    consumer=f"{action}.select",
                    query=query,
                    candidates=candidates(rows),
                    operation=OperationKind.SELECT,
                ),
                selector.apply(
                    consumer=f"{action}.rerank",
                    query=query,
                    candidates=candidates(rows),
                    operation=OperationKind.RERANK,
                ),
                selector.apply(
                    consumer=f"{action}.select",
                    query="Quantum neutrino oscillation measurement",
                    candidates=candidates(rows),
                    operation=OperationKind.SELECT,
                ),
            )
            assert [item.ref for item in selected] == [rows[0][0]]
            assert ranked[0].ref == rows[0][0] and len(ranked) == len(rows)
            assert unrelated == ()
    finally:
        await providers.close()
        await services.close()
