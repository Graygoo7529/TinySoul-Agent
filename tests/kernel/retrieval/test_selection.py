from __future__ import annotations

import json
import os
import asyncio
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
    SearchCandidate,
    SearchEvidence,
    SearchFailure,
    SearchFailureKind,
    SearchSemantic,
)
from tinysoul.kernel.retrieval.selection import CandidateSelector
from tinysoul.llm.protocol.responses import TaskResult, RawResponse, JsonAnswer


SAMPLES = (
    (
        "home.search",
        "如何检查 CSV 缺失值？",
        (
            (
                "home:skills@data",
                "数据检查",
                "用 pandas isna 检查 CSV 中的缺失值并统计每列缺失比例。",
            ),
            ("home:skills@cooking", "晚餐", "番茄炒蛋的配料和做法。"),
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
        SearchCandidate(ref, title, (SearchEvidence(ref, text),))
        for ref, title, text in rows
    )


def registry(action, implementation):
    return ModelUseRegistry(
        tuple(
            ModelUseDescriptor(
                f"{action}.{operation.value}", action, operation, (implementation,)
            )
            for operation in (ModelOperation.SELECT, ModelOperation.RANK)
        ),
        tuple(
            ModelUseBinding(
                f"{action}.{operation.value}",
                implementation,
                task_profile="selector"
                if implementation is ModelImplementation.LLM_TASK
                else None,
                use="decision"
                if implementation is ModelImplementation.STRUCTURED_DECISION
                else None,
            )
            for operation in (ModelOperation.SELECT, ModelOperation.RANK)
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
                "jev",
                ModelCapability.STRUCTURED_DECISION,
                (ServiceProviderBinding("typesafe", "jev-latest"),),
            ),
        ),
        (ServiceUse("decision", ModelCapability.STRUCTURED_DECISION, "jev"),),
    )


async def unused_invoke(call):
    raise AssertionError("A structured decision binding must not invoke LLM")


async def test_llm_selection_accepts_only_known_unique_subset_and_rank_requires_permutation():
    action, query, rows = SAMPLES[0]
    answer: JsonObject = {"ids": ["c1", "c0"]}
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
        consumer=f"{action}.rank",
        query=query,
        candidates=candidates(rows),
        operation=SearchSemantic.RANK,
    )
    assert [item.ref for item in ranked] == [rows[1][0], rows[0][0]]
    assert calls[0].consumer == f"{action}.rank"
    for invalid in (["c0"], ["c0", "c0"], ["unknown"]):
        answer["ids"] = to_json_value(invalid)
        with pytest.raises(SearchFailure):
            await selector.apply(
                consumer=f"{action}.rank",
                query=query,
                candidates=candidates(rows),
                operation=SearchSemantic.RANK,
            )
    answer["ids"] = []
    assert (
        await selector.apply(
            consumer=f"{action}.select",
            query=query,
            candidates=candidates(rows),
            operation=SearchSemantic.SELECT,
        )
        == ()
    )
    with pytest.raises(SearchFailure) as failure:
        await selector.apply(
            consumer=f"{action}.select",
            query=query,
            candidates=candidates(rows),
            operation=SearchSemantic.SELECT,
            input_max_chars=1,
        )
    assert failure.value.kind is SearchFailureKind.SCOPE_REQUIRED
    await services.close()


@pytest.mark.parametrize("action,query,rows", SAMPLES)
async def test_jev_uses_candidate_specific_questions_and_preserves_rank_membership(
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
        return httpx.Response(200, json={"model": "jev-test", "answers": answers})

    services = ModelServices(
        decision_settings(),
        env={"TYPESAFE_API_KEY": "test"},
        transport=httpx.MockTransport(respond),
    )
    selector = CandidateSelector(
        models=registry(action, ModelImplementation.STRUCTURED_DECISION),
        invoke=unused_invoke,
        services=services,
    )
    selected = await selector.apply(
        consumer=f"{action}.select",
        query=query,
        candidates=candidates(rows),
        operation=SearchSemantic.SELECT,
    )
    assert [item.ref for item in selected] == [rows[0][0]]
    ranked = await selector.apply(
        consumer=f"{action}.rank",
        query=query,
        candidates=candidates(rows),
        operation=SearchSemantic.RANK,
    )
    assert {item.ref for item in ranked} == {row[0] for row in rows}
    await services.close()


@pytest.mark.external
@pytest.mark.skipif(
    os.environ.get("TINYSOUL_EXTERNAL_JEV") != "1"
    or not os.environ.get("TYPESAFE_API_KEY"),
    reason="Explicit JEV external switch and credential required",
)
async def test_real_jev_representative_retrieval_quality():
    services = ModelServices(decision_settings(), env=os.environ)
    try:
        for action, query, rows in SAMPLES:
            selector = CandidateSelector(
                models=registry(action, ModelImplementation.STRUCTURED_DECISION),
                invoke=unused_invoke,
                services=services,
            )
            selected = await selector.apply(
                consumer=f"{action}.select",
                query=query,
                candidates=candidates(rows),
                operation=SearchSemantic.SELECT,
            )
            assert [item.ref for item in selected] == [rows[0][0]]
            ranked = await selector.apply(
                consumer=f"{action}.rank",
                query=query,
                candidates=candidates(rows),
                operation=SearchSemantic.RANK,
            )
            assert [item.ref for item in ranked] == [row[0] for row in rows]
            unrelated = await selector.apply(
                consumer=f"{action}.select",
                query="Explain the spectrum of a distant pulsar.",
                candidates=candidates(rows),
                operation=SearchSemantic.SELECT,
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
    from tinysoul.llm.execution.registry import ModelRegistry
    from tinysoul.llm.execution.model_chain import TaskSpecTable
    from tinysoul.llm.execution.task import LLMTaskRunner
    from tinysoul.llm.protocol.routing import TaskSpec, ModelChain, RetryPolicy
    from tinysoul.llm.provider.factory import build_provider_registry

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
        os.environ.get("TINYSOUL_RETRIEVAL_MODEL", "deepseek_flash")
    )
    provider_id = os.environ.get("TINYSOUL_RETRIEVAL_PROVIDER", "deepseek")
    binding = next(item for item in model.providers if item.provider_id == provider_id)
    provider = replace(config.provider(binding.provider_id), enabled=True)
    assert provider.configured_api_key(env), "The selected provider needs a credential"
    providers = await build_provider_registry((provider,), env=env)
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
                    operation=SearchSemantic.SELECT,
                ),
                selector.apply(
                    consumer=f"{action}.rank",
                    query=query,
                    candidates=candidates(rows),
                    operation=SearchSemantic.RANK,
                ),
                selector.apply(
                    consumer=f"{action}.select",
                    query="Quantum neutrino oscillation measurement",
                    candidates=candidates(rows),
                    operation=SearchSemantic.SELECT,
                ),
            )
            assert [item.ref for item in selected] == [rows[0][0]]
            assert ranked[0].ref == rows[0][0] and len(ranked) == len(rows)
            assert unrelated == ()
    finally:
        await providers.close()
        await services.close()
