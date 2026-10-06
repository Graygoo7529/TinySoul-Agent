"""Public schemas and examples checked against local owner/SDK/HTTP paths."""

from __future__ import annotations

import asyncio
import json
import sys
from collections import deque
from datetime import date
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi.encoders import jsonable_encoder
from jsonschema import Draft202012Validator
from pydantic import BaseModel

from tests.support.project import copy_initialized_project
from tinysoul.agent import Agent, HomeService
from tinysoul.agent.composition.builder import standard_agent
from tinysoul.agent.config import AgentSettings, OutputSettings
from tinysoul.gateway.endpoint import (
    EndpointEngine,
    EndpointEventBuffer,
    EndpointSettings,
)
from tinysoul.gateway.endpoint.http import create_endpoint_app
from tinysoul.gateway.endpoint.http.schemas import responses
from tinysoul.infra.config import ConfigController, ConfigEnvironment
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.kernel.interaction import QuestionContent
from tinysoul.llm.protocol.requests import TaskCall
from tinysoul.llm.protocol.responses import JsonAnswer, RawResponse, TaskResult
from tinysoul.llm.protocol.tools import ToolCallRecord, ToolKind
from tinysoul.plugins.memory import MemoryEngine, MemoryRef, MemorySettings
from tinysoul.plugins.memory.documents.models import EntityMemoryDocument, MemoryStatus
from tinysoul.plugins.workspace.services import WorkspaceService
from tinysoul.runtime import ObservationLevel

ROOT = Path(__file__).parents[3] / "docs" / "endpoint" / "contracts"
CONTRACT_MODELS: dict[str, type[BaseModel]] = {
    "runtime-status": responses.RuntimeStatusResponse,
    "command-receipt": responses.CommandReceiptResponse,
    "context-overview": responses.ContextOverviewResponse,
    "context-messages": responses.ContextMessagesResponse,
    "resource-locator": responses.ResourceLocatorResponse,
    "resource-resolve": responses.ResourceResolveResponse,
    "page": responses.PageResponse,
    "search-page": responses.SearchResponse,
    "turn-snapshot": responses.TurnResponse,
    "turn-list": responses.TurnListResponse,
    "interaction-page": responses.InteractionPageResponse,
    "configuration": responses.ConfigResponse,
    "config-mutation": responses.ConfigMutationResponse,
    "preset": responses.PresetResponse,
    "preset-list": responses.PresetListResponse,
    "job": responses.JobDetailResponse,
    "job-list": responses.JobListResponse,
    "job-output": responses.JobOutputResponse,
}
EXAMPLE_SCHEMAS = {
    "runtime-status": "runtime-status",
    "context-overview": "context-overview",
    "context-trace-page": "page",
    "context-messages": "context-messages",
    "home-effective": "page",
    "home-fragment": "page",
    "home-fragment-end": "page",
    "empty-page": "page",
    "memory-document": "page",
    "memory-fragment": "resource-resolve",
    "search-evidence": "search-page",
    "turn-waiting": "turn-snapshot",
    "turn-finished": "turn-snapshot",
    "interactions": "interaction-page",
    "config-apply": "config-mutation",
    "preset": "preset",
    "job-detail": "job",
    "job-output": "job-output",
}


def _load(path: Path) -> JsonObject:
    return to_json_object(json.loads(path.read_text(encoding="utf-8")))


def _validate(name: str, value: JsonObject) -> None:
    Draft202012Validator(_load(ROOT / "schemas" / f"{name}.json")).validate(value)
    model = CONTRACT_MODELS[name].model_validate(value, strict=True)
    assert model.model_dump(mode="json", exclude_unset=True) == value


@pytest.mark.parametrize("name", CONTRACT_MODELS)
def test_schema_is_exported_from_public_response_model(name: str) -> None:
    assert _load(ROOT / "schemas" / f"{name}.json") == {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        **CONTRACT_MODELS[name].model_json_schema(mode="serialization"),
    }


def test_examples_validate_and_core_envelopes_reject_empty_objects() -> None:
    for filename, schema in EXAMPLE_SCHEMAS.items():
        _validate(schema, _load(ROOT / "examples" / f"{filename}.json"))
    for value in _load(ROOT / "examples/config-views.json").values():
        assert isinstance(value, dict)
        _validate("configuration", value)
    for value in _load(ROOT / "examples/turn-receipts.json").values():
        assert isinstance(value, dict)
        _validate("command-receipt", value)
    for value in _load(ROOT / "examples/home-diff-memory-redirect.json").values():
        assert isinstance(value, dict)
        _validate("page", value)
    for name in ("page", "search-page", "turn-snapshot", "configuration", "job-output"):
        schema = _load(ROOT / "schemas" / f"{name}.json")
        assert list(Draft202012Validator(schema).iter_errors({}))
    question = _load(ROOT / "examples/turn-waiting.json")["question"]
    assert isinstance(question, dict)
    QuestionContent.from_json(question)


class _ContractLLM:
    """Only model outputs are fake; owners, SDK, execution and HTTP are real."""

    def __init__(self) -> None:
        self.calls = deque(
            (
                ("select_action_domains", {"domains": ["execution"]}),
                (
                    "execution.start",
                    {
                        "interpreter": "python",
                        "source_ref": "workspace:job.py",
                        "interactive": True,
                    },
                ),
                ("select_action_domains", {"domains": ["core"]}),
                (
                    "core.ask",
                    {
                        "text": "Choose a direction",
                        "options": [
                            {
                                "id": "a",
                                "label": "Execute",
                                "description": "Use the approved plan",
                            }
                        ],
                    },
                ),
                ("select_action_domains", {"domains": ["core"]}),
                ("core.answer", {"guide_blocks": [{"text": "Answer the user"}]}),
            )
        )

    async def invoke(self, call: TaskCall) -> TaskResult:
        return await self.run(call)

    async def run(self, call: TaskCall) -> TaskResult:
        if call.consumer == "home.search.rerank":
            answer = {"items": [{"id": "c0", "basis_ids": ["u0"]}]}
        elif not self.calls:
            answer = {"text": "Finished response"}
        else:
            name, args = self.calls.popleft()
            tool = ToolCallRecord(
                name,
                name,
                to_json_object(args),
                ToolKind.CONTROL
                if name == "select_action_domains"
                else ToolKind.ACTION,
            )
            return TaskResult.success(
                raw_response=RawResponse("", "fake", "fake", tool_calls=(tool,)),
                answer=None,
                tool_calls=(tool,),
            )
        return TaskResult.success(
            raw_response=RawResponse("{}", "fake", "fake"),
            answer=JsonAnswer(to_json_object(answer)),
            tool_calls=(),
        )


async def collect_contract_responses(root: Path) -> dict[str, JsonObject]:
    """Capture normal paths for handoff examples without provider/network calls."""
    copy_initialized_project(root)
    seed = MemoryEngine(settings=MemorySettings(root=root / "memory"))
    for cite, status, redirect in (
        ("project", MemoryStatus.ACTIVE, None),
        ("old-project", MemoryStatus.MERGED, MemoryRef.parse("memory:entity/project")),
    ):
        seed.write_document(
            EntityMemoryDocument(
                cite=cite,
                status=status,
                created_on=date(2026, 9, 29),
                updated_on=date(2026, 9, 29),
                content="Project notes",
                redirect_to=redirect,
            )
        )
    events = EndpointEventBuffer(capacity=256, max_bytes=1000000)
    agent = await Agent.assemble(
        standard_agent(root)
        .with_config_environment(
            ConfigEnvironment.from_project_root(
                root,
                env={},
                overrides={
                    "reflection.schedule.enabled": False,
                    "execution.enabled": True,
                    "execution.interpreters.python.executable": sys.executable,
                    "loop.user.max_cycles": 2,
                },
            )
        )
        .with_agent_settings(
            AgentSettings(
                interactive=False, output=OutputSettings(mode=ObservationLevel.VERBOSE)
            )
        )
        .with_output_sink(events)
        .with_llm_runner(_ContractLLM())
        .build()
    )
    await agent.start()
    runtime = agent.runtime
    endpoint = EndpointEngine(
        settings=EndpointSettings(token="x" * 32),
        events=events,
        gateway=runtime.gateway,
        services=runtime.service_access,
        config=runtime.configuration,
        available=lambda: runtime.is_available,
    )
    app = create_endpoint_app(endpoint, endpoint.settings)
    samples: dict[str, JsonObject] = {}
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {'x' * 32}"},
        ) as client:

            async def get(path: str, **params: str | int) -> JsonObject:
                response = await client.get(path, params=params)
                assert response.status_code == 200, response.text
                return to_json_object(response.json())

            async def post(path: str, body: JsonObject) -> JsonObject:
                response = await client.post(path, json=body)
                assert response.status_code in {200, 202}, response.text
                return to_json_object(response.json())

            applied = await post(
                "/v2/config/apply",
                {
                    "operations": [
                        {
                            "source_id": "project:configs/execution.toml",
                            "path": "execution.enabled",
                            "op": "set",
                            "value": True,
                        }
                    ]
                },
            )
            assert applied["state"] == "active" and applied["pending_reload"] is False
            samples["config-apply"] = applied
            for view in ("saved", "active"):
                _validate("configuration", await get("/v2/config", view=view))
            samples["preset"] = await post(
                "/v2/config/presets",
                {
                    "name": "Balanced",
                    "source": "active",
                    "include_budgets": False,
                },
            )
            _validate("preset-list", await get("/v2/config/presets"))
            home = agent.services.get(HomeService)
            actual_catalog = await get("/v2/home/catalog", view="actual", query="AGENT")
            actual_items = cast(list[JsonObject], actual_catalog["items"])
            assert any(item["ref"] == "home:top/agent/AGENT" for item in actual_items)
            effective_catalog = await get(
                "/v2/home/catalog", view="effective", query="AGENT"
            )
            effective_items = cast(list[JsonObject], effective_catalog["items"])
            assert not any(
                item["ref"] == "home:top/agent/AGENT" for item in effective_items
            )
            actual_content = await get(
                "/v2/home/content", ref="home:top/agent/AGENT", view="actual"
            )
            assert actual_content["items"]
            effective_content = await client.get(
                "/v2/home/content",
                params={"ref": "home:top/agent/AGENT", "view": "effective"},
            )
            assert effective_content.status_code == 404, effective_content.text
            await home.write_top("home:top/agent/contract", "Workspace guidance\n")
            samples["home-effective"] = await get(
                "/v2/home/content", ref="home:top/agent/contract"
            )
            samples["empty-page"] = await get(
                "/v2/home/catalog", query="absent-contract-resource"
            )
            samples["search-evidence"] = await post(
                "/v2/home/search",
                {
                    "source": {"kind": "refs", "refs": ["home:top/agent/contract"]},
                    "steps": [
                        {
                            "op": "rerank",
                            "criterion": "Workspace guidance",
                            "context": "none",
                        }
                    ],
                },
            )
            samples["model-observation"] = next(
                event.to_json()
                for event in events.replay(
                    after=0, mode=ObservationLevel.VERBOSE
                ).events
                if event.name == "retrieval.model.invoked"
            )
            await home.write_top("home:top/agent/long-contract", "Long content " * 140)
            page = await get(
                "/v2/home/content", ref="home:top/agent/long-contract", max_chars=1024
            )
            samples["home-fragment"] = page
            assert page["items"] == [] and "next_continuation" in page
            fragments = []
            for _ in range(100):
                fragment = page.get("content_fragment")
                if isinstance(fragment, dict):
                    fragments.append(str(fragment["text"]))
                    samples["home-fragment-end"] = page
                token = page.get("next_continuation")
                if not isinstance(token, str):
                    break
                page = await get(
                    "/v2/home/content",
                    ref="home:top/agent/long-contract",
                    max_chars=1024,
                    continuation=token,
                )
            else:
                pytest.fail("Home fragment did not finish")
            assert json.loads("".join(fragments))["text"] == "Long content " * 140
            samples["memory-document"] = await get(
                "/v2/memory/document", ref="memory:entity/project"
            )
            samples["home-diff-memory-redirect"] = {
                "home_diff": await get("/v2/home/diff", ref="home:top/agent/contract"),
                "memory_redirect": await get(
                    "/v2/memory/document", ref="memory:entity/old-project"
                ),
            }
            samples["capabilities"] = {
                "acp": await get("/v2/subagent"),
                "mcp": await get("/v2/expand/servers"),
            }
            await agent.services.get(WorkspaceService).write_text(
                "workspace:job.py",
                "import sys\nprint('ready', flush=True)\nprint('notice', file=sys.stderr, flush=True)\nsys.stdin.read()\n",
            )
            samples["turn-receipts"] = {
                "create": await post(
                    "/v2/requests",
                    {
                        "text": "Run the prepared job and ask before proceeding",
                        "command_id": "contract-turn",
                    },
                )
            }
            handle = agent.commands.request("contract-turn")
            assert handle is not None
            async with asyncio.timeout(10):
                while handle.question is None or handle.budget_request is None:
                    assert not handle.done, handle.result
                    await asyncio.sleep(0.01)
            assert handle.turn_id is not None
            samples["turn-waiting"] = await get("/v2/requests/contract-turn")
            snapshot = agent.request_snapshot("contract-turn")
            assert snapshot is not None
            assert samples["turn-waiting"] == snapshot.to_json()
            directory = await get("/v2/requests")
            _validate("turn-list", directory)
            assert directory["items"] == [snapshot.summary_json()]
            samples["context-overview"] = await get(
                "/v2/requests/contract-turn/context"
            )
            installed_background = await get(
                "/v2/requests/contract-turn/context/background", max_chars=64000
            )
            assert installed_background["source"] == "installed"
            assert installed_background["snapshot_available"] is True
            installed_entries = cast(list[JsonObject], installed_background["items"])
            loaded_agent = next(
                item
                for item in installed_entries
                if item["ref"] == "home:top/agent/AGENT"
            )
            assert isinstance(loaded_agent["content"], str) and loaded_agent["content"]
            samples["context-messages"] = await get(
                "/v2/requests/contract-turn/context/segments/inputs"
            )
            samples["context-trace-page"] = await get(
                "/v2/requests/contract-turn/context/inspect",
                ref=f"turn:trace/{handle.turn_id}",
            )
            samples["runtime-status"] = await get("/v2/status")
            samples["memory-fragment"] = await get(
                "/v2/resources/resolve",
                ref="memory:current#notes",
                turn_id=handle.turn_id,
            )
            _validate("job-list", await get("/v2/requests/contract-turn/jobs"))
            snapshots = agent.turn_jobs("contract-turn")
            assert snapshots
            job_path = f"/v2/requests/contract-turn/jobs/{snapshots[0].job_id}"
            async with asyncio.timeout(5):
                while True:
                    output = await get(job_path + "/output")
                    if "ready" in str(output["items"]) and "notice" in str(
                        output["items"]
                    ):
                        break
                    await asyncio.sleep(0.01)
            samples["job-output"] = output
            token = output["next_continuation"]
            assert isinstance(token, str)
            tail = await get(job_path + "/output", continuation=token)
            assert tail["items"] == [
                {"channel": "stdout", "text": ""},
                {"channel": "stderr", "text": ""},
            ]
            samples["job-detail"] = await get(job_path)
            await post(job_path + "/stop", {})
            question, budget = handle.question, handle.budget_request
            assert question is not None and budget is not None
            await post(
                "/v2/requests/contract-turn/reply",
                {
                    "question_id": question.question_id,
                    "answer": {
                        "kind": "choice",
                        "option_id": "a",
                        "comment": "Proceed",
                    },
                },
            )
            await post(
                "/v2/requests/contract-turn/grant",
                {"budget_request_id": budget.request_id, "count": 1},
            )
            result = await asyncio.wait_for(handle.wait(), 10)
            samples["turn-finished"] = await get("/v2/requests/contract-turn")
            assert samples["turn-finished"]["result"] == result.to_json()
            assert result.to_json()["status"] == "answered"
            # Completion persists the installed content. Reading it later does
            # not reopen Home, even after the runtime overlay has changed.
            await agent.services.get(HomeService).write_top(
                "home:top/agent/AGENT", "Changed after completion\n", overwrite=True
            )
            committed_background = await get(
                f"/v2/session/turns/{handle.turn_id}/background",
                day=str(installed_background["day"]),
                max_chars=64000,
            )
            assert committed_background["source"] == "session"
            assert committed_background["snapshot_available"] is True
            committed_entries = cast(list[JsonObject], committed_background["items"])
            assert (
                next(
                    item
                    for item in committed_entries
                    if item["ref"] == loaded_agent["ref"]
                )
                == loaded_agent
            )
            assert any(item["owner"] == "memory" for item in committed_entries)
            interaction_page = await get(
                "/v2/requests/contract-turn/interactions", limit=1
            )
            samples["interactions"] = interaction_page
            items = []
            for _ in range(100):
                _validate("interaction-page", interaction_page)
                values = interaction_page["items"]
                assert isinstance(values, list)
                items.extend(values)
                token = interaction_page.get("next_continuation")
                if not isinstance(token, str):
                    break
                interaction_page = await get(
                    "/v2/requests/contract-turn/interactions",
                    limit=1,
                    continuation=token,
                )
            questions = [
                item
                for item in items
                if isinstance(item, dict) and item.get("role") == "agent.question"
            ]
            replies = [
                item
                for item in items
                if isinstance(item, dict) and item.get("role") == "user.reply"
            ]
            assert questions and replies
            assert questions[0]["question_id"] == replies[0]["question_id"]
            samples["question-reply"] = {"question": questions[0], "reply": replies[0]}
            openapi = await get("/openapi.json")
            components = openapi["components"]
            assert isinstance(components, dict)
            schemas = components["schemas"]
            assert isinstance(schemas, dict)
            for model in CONTRACT_MODELS.values():
                schema = schemas.get(model.__name__)
                assert isinstance(schema, dict), model.__name__
                expected = model.model_json_schema(mode="serialization")
                properties = json.loads(
                    json.dumps(schema["properties"])
                    .replace("#/components/schemas/", "#/$defs/")
                    .replace("#/$defs/JsonValue-Output", "#/$defs/JsonValue")
                )
                # FastAPI omits null schema defaults; nullable value types remain.
                assert properties == jsonable_encoder(
                    expected["properties"], exclude_none=True
                ), (model.__name__, properties, expected["properties"])
                assert schema.get("required", []) == expected.get("required", [])
    finally:
        await agent.shutdown()
    # A minimal local configuration keeps the source/preset examples small while
    # retaining the controller's complete serialization, including null values.
    minimal = root.parent / "configuration"
    minimal.mkdir()
    (minimal / "tinysoul.toml").write_text(
        "[execution]\nenabled = true\n", encoding="utf-8"
    )
    controller = ConfigController(
        root=minimal, environment=ConfigEnvironment.from_project_root(minimal, env={})
    )
    samples["config-views"] = {
        view: controller.status(view=view) for view in ("saved", "active")
    }
    samples["preset"] = await controller.save_preset(
        name="Balanced", include_budgets=False
    )
    await controller.close()
    return samples


async def test_real_owner_http_responses_match_handoff(tmp_path: Path) -> None:
    samples = await collect_contract_responses(tmp_path / "project")
    examples = {name: _load(ROOT / "examples" / f"{name}.json") for name in samples}
    for name, value in samples.items():
        assert set(value) == set(examples[name]), name
    for filename, schema in EXAMPLE_SCHEMAS.items():
        _validate(schema, samples[filename])
    for name in ("home_diff", "memory_redirect"):
        value = samples["home-diff-memory-redirect"][name]
        assert isinstance(value, dict)
        _validate("page", value)
    for collection in (samples, examples):
        assert collection["turn-waiting"]["state"] == "waiting"
        assert isinstance(collection["turn-waiting"]["question"], dict)
        assert isinstance(collection["turn-waiting"]["budget_request"], dict)
        result = collection["turn-finished"]["result"]
        assert isinstance(result, dict) and result["status"] == "answered"
        assert collection["home-fragment"]["items"] == []
        assert "next_continuation" in collection["home-fragment"]
        assert "content_fragment" in collection["home-fragment-end"]
        assert "next_continuation" not in collection["home-fragment-end"]
        assert collection["config-apply"]["state"] == "active"
        assert collection["config-apply"]["pending_reload"] is False
        assert collection["model-observation"]["name"] == "retrieval.model.invoked"
        question, reply = collection["question-reply"].values()
        assert isinstance(question, dict) and isinstance(reply, dict)
        assert question["question_id"] == reply["question_id"]
        assert question["ref"] == reply["reply_to"]
