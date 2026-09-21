from __future__ import annotations
import asyncio
import sys
from time import monotonic
from tinysoul.agent.composition.assembly import AgentAssembly
from tinysoul.kernel.loop.turn import TurnOutcome

from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from pypdf import PdfWriter

from tinysoul.agent.config import AgentSettings
from tinysoul.gateway.project.initializer import ProjectConfigProfile
from tinysoul.agent.composition.builder import AgentBuilder
from tinysoul.gateway.endpoint.host import mount_endpoint
from tinysoul.gateway.endpoint import EndpointSettings
from tinysoul.gateway.endpoint.http import create_endpoint_app
from tinysoul.infra.config import ConfigEnvironment
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.llm.protocol.requests import TaskCall
from tinysoul.llm.failures import LLMFailureKind
from tinysoul.llm.protocol.responses import JsonAnswer, RawResponse, TaskResult
from tinysoul.llm.protocol.tools import ToolCallRecord, ToolKind
from tinysoul.kernel.loop import (
    LoopControlKind,
    LoopSettings,
    TurnSettings,
    TurnCompletion,
    build_control_request_signal,
)
from tinysoul.runtime import (
    ObservationLevel,
    RUNTIME_STARTUP_FAILED,
    RunLevel,
    RuntimeException,
    RuntimeTransferAction,
    SignalBus,
)
from tests.support.project import copy_initialized_project
from tinysoul.kernel.loop.assembly import TurnProfile
from tinysoul.plugins.reflection.builder import ReflectionBuilder
from tinysoul.plugins.home.services import HomeReviewService
from tinysoul.plugins.memory.services import (
    MemoryKnowledgeService,
    MemoryService,
    MemoryReadService,
)
from tinysoul.kernel.registration import RegistrationError


class FakeLLM:
    def __init__(self, results: tuple[TaskResult, ...]) -> None:
        self.results = deque(results)
        self.calls: list[TaskCall] = []

    async def run(self, call: TaskCall) -> TaskResult:
        self.calls.append(call)
        return self.results.popleft()


@pytest.fixture
async def endpoint_assemblies() -> AsyncIterator[list[AgentAssembly]]:
    assemblies: list[AgentAssembly] = []
    try:
        yield assemblies
    finally:
        for assembly in reversed(assemblies):
            await assembly.close()


async def test_three_scenarios_have_independent_policies_and_owner_services(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "project"
    copy_initialized_project(root)
    profiles: list[TurnProfile] = []
    original = ReflectionBuilder.build

    def capture(builder):
        result = original(builder)
        profiles.extend(result.profiles)
        return result

    monkeypatch.setattr(ReflectionBuilder, "build", capture)
    config = ConfigEnvironment.from_project_root(
        root,
        env={},
        overrides={
            "capabilities.expand.servers.local.enabled": True,
            "capabilities.expand.servers.local.command": sys.executable,
            "capabilities.subagent.agents.local.enabled": True,
            "capabilities.subagent.agents.local.command": sys.executable,
        },
    )
    app = await (
        AgentBuilder(root)
        .with_config_environment(config)
        .with_agent_settings(AgentSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
        .build()
    )
    try:
        user = app.generation_handle.snapshot().generation.user_turn.profile
        home, memory = profiles
        identifiers = [
            {name for _, name in profile.action.action_identifiers()}
            for profile in (user, home, memory)
        ]
        assert "home.resource.read" in identifiers[0]
        assert "home.diff" in identifiers[1] and "home.review" in identifiers[1]
        assert (
            "memory.write_daily" in identifiers[2] and "memory.write" in identifiers[2]
        )
        assert not identifiers[0].intersection(
            {"home.diff", "home.review", "memory.write", "memory.write_daily"}
        )
        assert "memory.memorize" not in identifiers[2]
        for actions in identifiers:
            assert {
                "expand.search",
                "expand.call",
                "subagent.connect",
                "subagent.delegate",
                "subagent.respond",
            } <= actions
        assert home.services.get(HomeReviewService)
        assert home.services.get(MemoryService)
        assert memory.services.get(MemoryKnowledgeService)
        assert memory.services.get(MemoryReadService)
        for profile, denied in (
            (user, HomeReviewService),
            (user, MemoryKnowledgeService),
            (home, MemoryKnowledgeService),
            (memory, HomeReviewService),
            (memory, MemoryService),
        ):
            with pytest.raises(RegistrationError):
                profile.services.get(denied)
    finally:
        await app.close()


@dataclass
class _CompletionRecorder:
    completions: list[TurnCompletion] = field(default_factory=list)

    async def handle(self, completion: TurnCompletion) -> None:
        self.completions.append(completion)


def test_agent_test_config_isolates_all_mutable_roots(tmp_path: Path) -> None:
    config = _test_config(tmp_path)

    home = config.section_tree("home")
    memory = config.section_tree("memory")
    session = config.section_tree("session")
    workspace = config.section_tree("workspace")
    reflection = config.section_tree("reflection")

    assert home["root"] == str(tmp_path / "home")
    assert home["runtime_root"] == str(tmp_path / "runtime" / "home")
    assert memory["root"] == str(tmp_path / "memory")
    assert session["root"] == str(tmp_path / "runtime" / "session")
    assert workspace["root"] == str(tmp_path / "runtime" / "workspace")
    assert reflection["archive_root"] == str(tmp_path / "archive")


async def test_agent_builder_cleans_project_capability_staging_on_startup(
    tmp_path: Path,
) -> None:
    stale = tmp_path / "runtime" / ".staging" / "web-interrupted" / "source.html"
    stale.parent.mkdir(parents=True)
    stale.write_text("stale", encoding="utf-8")
    config = _test_config(
        tmp_path,
        overrides={
            "capabilities.resource.convert_with_markitdown.enabled": False,
            "capabilities.resource.convert_with_pypdf.enabled": False,
            "capabilities.web.search_by_kimi.enabled": False,
            "capabilities.web.discover_pages.enabled": False,
            "capabilities.web.fetch_with_defuddle.enabled": False,
            "capabilities.web.fetch_with_trafilatura.enabled": False,
        },
    )

    (
        await AgentBuilder(root=tmp_path)
        .with_config_environment(config)
        .with_agent_settings(AgentSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
        .build()
    )

    staging = tmp_path / "runtime" / ".staging"
    assert staging.is_dir()
    assert tuple(staging.iterdir()) == ()


async def test_agent_builder_mounts_endpoint_as_service_and_model_output_source(
    tmp_path: Path,
) -> None:
    app = (
        await AgentBuilder(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_agent_settings(AgentSettings(interactive=True))
        .with_llm_runner(FakeLLM(()))
        .build()
    )
    endpoint = mount_endpoint(app, EndpointSettings(token="x" * 32))
    entered, release = asyncio.Event(), asyncio.Event()

    class ActivationGate:
        async def start(self) -> None:
            entered.set()
            await release.wait()

        async def stop(self) -> None:
            pass

    assert app.input_sources == () and len(app.services) == 1
    assert app.observations.mode.value == "model"
    app.mount_service(ActivationGate())
    activating = asyncio.create_task(app.activate())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert (await endpoint.runtime.status())["ready"] is False
        from tinysoul.gateway.endpoint.errors import EndpointRequestError

        with pytest.raises(EndpointRequestError) as rejected:
            await endpoint.configuration.status()
        assert rejected.value.code == "service.unavailable"
        release.set()
        await activating
        assert (await endpoint.runtime.status())["ready"] is True
        assert "runtime" in await endpoint.configuration.status()
        app.stop_accepting()
        assert (await endpoint.runtime.status())["ready"] is False
    finally:
        release.set()
        await asyncio.gather(activating, return_exceptions=True)
        await app.close()


async def test_standard_project_starts_without_credentials_and_rejects_provider_enable(
    tmp_path: Path,
    endpoint_assemblies: list[AgentAssembly],
) -> None:
    project_root = tmp_path / "project"
    copy_initialized_project(project_root)
    app = (
        await AgentBuilder(root=project_root)
        .with_config_environment(
            ConfigEnvironment.from_project_root(project_root, env={})
        )
        .with_agent_settings(AgentSettings(interactive=False))
        .build()
    )
    endpoint = mount_endpoint(app, EndpointSettings(token="x" * 32))
    endpoint_assemblies.append(app)
    await app.activate()
    client = TestClient(create_endpoint_app(endpoint, endpoint.settings))
    headers = {"Authorization": f"Bearer {'x' * 32}"}

    runtime_before = _json_object(
        client.get("/v2/config", headers=headers).json()["runtime"]
    )
    llm_status = _json_object(runtime_before["llm"])
    providers = llm_status["providers"]
    assert isinstance(providers, list)
    deepseek = next(
        item
        for item in providers
        if isinstance(item, dict) and item.get("id") == "deepseek"
    )
    assert deepseek == {
        "id": "deepseek",
        "credential_state": "missing",
        "api_key_envs": ["DEEPSEEK_API_KEY"],
    }

    response = client.patch(
        "/v2/config",
        headers=headers,
        json={
            "operations": [
                {
                    "source_id": "project:configs/llm/providers.toml",
                    "path": "llm.providers.deepseek.enabled",
                    "op": "set",
                    "value": True,
                }
            ]
        },
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "config.invalid"
    assert "DEEPSEEK_API_KEY" in error["message"]
    assert error["details"]["key"] == "llm.providers.deepseek.api_key_envs"
    runtime_after = client.get("/v2/config", headers=headers).json()["runtime"]
    assert runtime_after["generation_id"] == runtime_before["generation_id"]
    providers_path = project_root / "configs" / "llm" / "providers.toml"
    assert "enabled = true" not in providers_path.read_text(encoding="utf-8")

    credential_response = client.patch(
        "/v2/config",
        headers=headers,
        json={
            "operations": [
                {
                    "source_id": "dotenv",
                    "path": "DEEPSEEK_API_KEY",
                    "op": "set",
                    "value": "configured",
                }
            ]
        },
    )
    assert credential_response.status_code == 200
    assert client.post("/v2/config/reload", headers=headers).status_code == 200
    configured_runtime = client.get("/v2/config", headers=headers).json()["runtime"]
    configured_llm = _json_object(configured_runtime["llm"])
    configured_providers = configured_llm["providers"]
    assert isinstance(configured_providers, list)
    assert (
        next(
            item
            for item in configured_providers
            if isinstance(item, dict) and item.get("id") == "deepseek"
        )["credential_state"]
        == "configured"
    )

    enabled_response = client.patch(
        "/v2/config",
        headers=headers,
        json={
            "operations": [
                {
                    "source_id": "project:configs/llm/providers.toml",
                    "path": "llm.providers.deepseek.enabled",
                    "op": "set",
                    "value": True,
                }
            ]
        },
    )
    assert enabled_response.status_code == 200
    assert "enabled = true" in providers_path.read_text(encoding="utf-8")


async def test_development_project_requires_credentials_for_enabled_providers(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "development-project"
    copy_initialized_project(
        project_root,
        config_profile=ProjectConfigProfile.DEVELOPMENT,
    )

    with pytest.raises(RuntimeException) as error:
        (
            await AgentBuilder(root=project_root)
            .with_config_environment(
                ConfigEnvironment.from_project_root(project_root, env={})
            )
            .with_agent_settings(AgentSettings(interactive=False))
            .build()
        )

    assert error.value.reason == RUNTIME_STARTUP_FAILED
    assert error.value.payload["kind"] == LLMFailureKind.CONFIGURATION_FAILED


async def test_endpoint_config_reload_rebuilds_generation_and_keeps_event_buffer(
    tmp_path: Path,
    endpoint_assemblies: list[AgentAssembly],
) -> None:
    project_root = tmp_path / "project"
    copy_initialized_project(project_root)
    app = (
        await AgentBuilder(root=project_root)
        .with_config_environment(ConfigEnvironment.from_project_root(project_root))
        .with_agent_settings(AgentSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
        .build()
    )
    endpoint = mount_endpoint(
        app,
        EndpointSettings(
            token="x" * 32,
            websocket_heartbeat_seconds=0.05,
        ),
    )
    endpoint_assemblies.append(app)
    await app.activate()
    events = endpoint.events
    before = (await endpoint.configuration.status())["runtime"]
    after_sequence = events.latest_sequence

    client = TestClient(create_endpoint_app(endpoint, endpoint.settings))
    with client.websocket_connect("/v2/events/ws") as websocket:

        def receive_event_names() -> tuple[str, ...]:
            deadline = monotonic() + 5
            while monotonic() < deadline:
                message = to_json_object(websocket.receive_json())
                if message.get("type") == "events":
                    raw_events = message.get("events")
                    assert isinstance(raw_events, list)
                    names: list[str] = []
                    for raw_event in raw_events:
                        event = to_json_object(raw_event)
                        name = event.get("name")
                        assert isinstance(name, str)
                        names.append(name)
                    return tuple(names)
            raise AssertionError("WebSocket did not publish an event page")

        websocket.send_json(
            {
                "token": "x" * 32,
                "after": after_sequence,
                "mode": "normal",
            }
        )
        assert websocket.receive_json()["type"] == "authenticated"
        response = client.patch(
            "/v2/config",
            headers={"Authorization": f"Bearer {'x' * 32}"},
            json={
                "operations": [
                    {
                        "source_id": "project:configs/action/routing.toml",
                        "path": "action.llm_action.timeout_seconds",
                        "op": "set",
                        "value": 30.0,
                    },
                    {
                        "source_id": (
                            "project-document:action.catalog:configs/action/catalog/"
                            "workspace/actions/read.toml"
                        ),
                        "path": "visibility.default",
                        "op": "set",
                        "value": False,
                    },
                    {
                        "source_id": (
                            "project-document:action.catalog:configs/action/catalog/"
                            "workspace/actions/read.toml"
                        ),
                        "path": "tool.description",
                        "op": "set",
                        "value": (
                            "Read one project workspace resource for the current task."
                        ),
                    },
                ]
            },
        )
        assert response.status_code == 200
        assert response.json()["state"] == "saved"
        assert (await endpoint.configuration.status())["runtime"] == before
        reloaded = client.post(
            "/v2/config/reload",
            headers={"Authorization": f"Bearer {'x' * 32}"},
        )
        assert reloaded.status_code == 200
        result = reloaded.json()
        assert isinstance(result, dict)
        websocket_event_names = receive_event_names()
        websocket_completed_names = receive_event_names()
        for _ in range(12):
            if "config.activation.completed" in websocket_completed_names:
                break
            websocket_completed_names = receive_event_names()

    after = (await endpoint.configuration.status())["runtime"]
    action_catalog = client.get(
        "/v2/config/actions",
        headers={"Authorization": f"Bearer {'x' * 32}"},
    )
    assert isinstance(before, dict)
    assert isinstance(after, dict)
    assert result["state"] == "active"
    assert result["generation_id"] == after["generation_id"]
    assert after["generation_id"] != before["generation_id"]
    assert after["activity"] == "idle"
    assert endpoint.events is events
    assert action_catalog.status_code == 200
    assert any(
        item["id"] == "workspace.analyze"
        and item["backend"]["kind"] == "llm_action"
        and item["available"] is True
        for item in action_catalog.json()["actions"]
    )
    assert any(
        item["id"] == "workspace.read"
        and item["tool"]["description"]
        == "Read one project workspace resource for the current task."
        and item["selection"]["enabled"] is False
        and item["selection"]["source"] == "action.visibility.default"
        and item["supported"] is True
        and item["available"] is False
        and "visibility.default" in item["source"]["editable_paths"]
        and item["source"]["document_kind"] == "action"
        for item in action_catalog.json()["actions"]
    )
    assert any(
        item["id"] == "web.search_by_kimi" and item["available"] is False
        for item in action_catalog.json()["actions"]
    )

    assert any(
        item["id"] == "workspace" and item["source"]["document_kind"] == "domain"
        for item in action_catalog.json()["domains"]
    )
    assert "timeout_seconds = 30.0" in (
        project_root / "configs" / "action" / "routing.toml"
    ).read_text(encoding="utf-8")
    assert "Read one project workspace resource for the current task." in (
        project_root
        / "configs"
        / "action"
        / "catalog"
        / "workspace"
        / "actions"
        / "read.toml"
    ).read_text(encoding="utf-8")
    assert "default = false" in (
        project_root
        / "configs"
        / "action"
        / "catalog"
        / "workspace"
        / "actions"
        / "read.toml"
    ).read_text(encoding="utf-8")
    invalid = client.patch(
        "/v2/config",
        headers={"Authorization": f"Bearer {'x' * 32}"},
        json={
            "operations": [
                {
                    "source_id": (
                        "project-document:action.catalog:configs/action/catalog/"
                        "workspace/actions/read.toml"
                    ),
                    "path": "tool.description",
                    "op": "set",
                    "value": "",
                }
            ]
        },
    )
    assert invalid.status_code == 422
    invalid_body = invalid.json()
    assert invalid_body["error"]["details"]["source"].startswith(
        "project-document:action.catalog:"
    )
    invalid_timeout = client.patch(
        "/v2/config",
        headers={"Authorization": f"Bearer {'x' * 32}"},
        json={
            "operations": [
                {
                    "source_id": (
                        "project-document:action.catalog:configs/action/catalog/"
                        "workspace/actions/read.toml"
                    ),
                    "path": "runtime.timeout_seconds",
                    "op": "set",
                    "value": -1,
                }
            ]
        },
    )
    assert invalid_timeout.status_code == 422
    assert invalid_timeout.json()["error"]["details"]["key"].endswith(
        "runtime.timeout_seconds"
    )
    current_runtime = (await endpoint.configuration.status())["runtime"]
    assert isinstance(current_runtime, dict)
    assert current_runtime["generation_id"] == after["generation_id"]
    assert "Read one project workspace resource for the current task." in (
        project_root
        / "configs"
        / "action"
        / "catalog"
        / "workspace"
        / "actions"
        / "read.toml"
    ).read_text(encoding="utf-8")
    activation_events = events.replay(
        after=after_sequence,
        mode=ObservationLevel.NORMAL,
        limit=20,
    )
    assert [
        event.name
        for event in activation_events.events
        if event.name.startswith("config.activation.")
    ] == [
        "config.activation.started",
        "config.activation.completed",
    ]
    assert websocket_event_names == ("config.activation.started",)
    assert websocket_completed_names == ("config.activation.completed",)


async def test_endpoint_action_activation_inherits_and_restores_runtime_policy(
    tmp_path: Path,
    endpoint_assemblies: list[AgentAssembly],
) -> None:
    project_root = tmp_path / "project"
    copy_initialized_project(project_root)
    app = (
        await AgentBuilder(root=project_root)
        .with_config_environment(ConfigEnvironment.from_project_root(project_root))
        .with_agent_settings(AgentSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
        .build()
    )
    endpoint = mount_endpoint(app, EndpointSettings(token="x" * 32))
    endpoint_assemblies.append(app)
    await app.activate()
    client = TestClient(create_endpoint_app(endpoint, endpoint.settings))
    headers = {"Authorization": f"Bearer {'x' * 32}"}
    domain_source = (
        "project-document:action.catalog:configs/action/catalog/workspace/domain.toml"
    )
    action_source = (
        "project-document:action.catalog:"
        "configs/action/catalog/workspace/actions/read.toml"
    )
    domain_path = (
        project_root / "configs" / "action" / "catalog" / "workspace" / "domain.toml"
    )

    runtime_before = _json_object((await endpoint.configuration.status())["runtime"])
    generation_before = runtime_before["generation_id"]
    invalid = client.patch(
        "/v2/config",
        headers=headers,
        json={
            "operations": [
                {
                    "source_id": domain_source,
                    "path": "visibility.default",
                    "op": "set",
                    "value": "false",
                }
            ]
        },
    )
    assert invalid.status_code == 422
    runtime_after_invalid = _json_object(
        (await endpoint.configuration.status())["runtime"]
    )
    assert runtime_after_invalid["generation_id"] == generation_before
    assert "default = true" in domain_path.read_text(encoding="utf-8")

    routed = client.patch(
        "/v2/config",
        headers=headers,
        json={
            "operations": [
                {
                    "source_id": "project:configs/action/routing.toml",
                    "path": "action.llm_action.overrides",
                    "op": "set",
                    "value": [
                        {
                            "action_id": "workspace.analyze",
                            "task_profile": "llm_action",
                        }
                    ],
                }
            ]
        },
    )
    assert routed.status_code == 200

    domain_disabled = client.patch(
        "/v2/config",
        headers=headers,
        json={
            "operations": [
                {
                    "source_id": domain_source,
                    "path": "visibility.default",
                    "op": "set",
                    "value": False,
                }
            ]
        },
    )
    assert domain_disabled.status_code == 200
    assert client.post("/v2/config/reload", headers=headers).status_code == 200
    disabled_read = _action_catalog_item(client, headers, "workspace.read")
    disabled_analysis = _action_catalog_item(client, headers, "workspace.analyze")
    disabled_runtime = _json_object(disabled_read["selection"])
    assert disabled_runtime["enabled"] is False
    assert disabled_runtime["source"] == "domain.visibility.default"
    assert disabled_read["supported"] is True
    assert disabled_read["available"] is False
    assert disabled_analysis["available"] is False
    assert "workspace.analyze" in (
        project_root / "configs" / "action" / "routing.toml"
    ).read_text(encoding="utf-8")

    action_enabled = client.patch(
        "/v2/config",
        headers=headers,
        json={
            "operations": [
                {
                    "source_id": action_source,
                    "path": "visibility.default",
                    "op": "set",
                    "value": True,
                }
            ]
        },
    )
    assert action_enabled.status_code == 200
    assert client.post("/v2/config/reload", headers=headers).status_code == 200
    enabled_read = _action_catalog_item(client, headers, "workspace.read")
    enabled_runtime = _json_object(enabled_read["selection"])
    assert enabled_runtime["enabled"] is True
    assert enabled_runtime["source"] == "action.visibility.default"
    assert enabled_read["available"] is True

    action_inherited = client.patch(
        "/v2/config",
        headers=headers,
        json={
            "operations": [
                {
                    "source_id": action_source,
                    "path": "visibility.default",
                    "op": "delete",
                }
            ]
        },
    )
    assert action_inherited.status_code == 200
    assert client.post("/v2/config/reload", headers=headers).status_code == 200
    inherited_read = _action_catalog_item(client, headers, "workspace.read")
    inherited_runtime = _json_object(inherited_read["selection"])
    assert inherited_runtime["enabled"] is False
    assert inherited_runtime["source"] == "domain.visibility.default"
    assert inherited_read["available"] is False

    domain_default = client.patch(
        "/v2/config",
        headers=headers,
        json={
            "operations": [
                {
                    "source_id": domain_source,
                    "path": "visibility.default",
                    "op": "delete",
                }
            ]
        },
    )
    assert domain_default.status_code == 200
    assert client.post("/v2/config/reload", headers=headers).status_code == 200
    restored_read = _action_catalog_item(client, headers, "workspace.read")
    restored_analysis = _action_catalog_item(client, headers, "workspace.analyze")
    restored_runtime = _json_object(restored_read["selection"])
    assert restored_runtime["enabled"] is True
    assert restored_runtime["source"] == "default"
    assert restored_read["available"] is True
    assert restored_analysis["available"] is True
    assert "default =" not in domain_path.read_text(encoding="utf-8")

    answer_disabled = client.patch(
        "/v2/config",
        headers=headers,
        json={
            "operations": [
                {
                    "source_id": (
                        "project-document:action.catalog:"
                        "configs/action/catalog/core/actions/answer.toml"
                    ),
                    "path": "visibility.default",
                    "op": "set",
                    "value": False,
                }
            ]
        },
    )
    assert answer_disabled.status_code == 200
    assert client.post("/v2/config/reload", headers=headers).status_code == 200
    disabled_answer = _action_catalog_item(client, headers, "core.answer")
    disabled_answer_runtime = _json_object(disabled_answer["selection"])
    assert disabled_answer_runtime["enabled"] is False
    assert disabled_answer["supported"] is True
    assert disabled_answer["available"] is False


async def test_endpoint_provider_switch_preserves_model_options_and_rolls_back_incompatible_adapter(
    tmp_path: Path,
    endpoint_assemblies: list[AgentAssembly],
) -> None:
    project_root = tmp_path / "project"
    copy_initialized_project(project_root)
    providers_path = project_root / "configs" / "llm" / "providers.toml"
    with providers_path.open("a", encoding="utf-8") as providers:
        providers.write(
            "\n[llm.providers.openai_proxy]\n"
            "enabled = true\n"
            'adapters = ["openai"]\n'
            'base_url = "https://proxy.example/v1"\n'
            'api_key_envs = ["OPENAI_PROXY_API_KEY"]\n'
        )
    app = (
        await AgentBuilder(root=project_root)
        .with_config_environment(ConfigEnvironment.from_project_root(project_root))
        .with_agent_settings(AgentSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
        .build()
    )
    endpoint = mount_endpoint(app, EndpointSettings(token="x" * 32))
    endpoint_assemblies.append(app)
    await app.activate()
    client = TestClient(create_endpoint_app(endpoint, endpoint.settings))
    headers = {"Authorization": f"Bearer {'x' * 32}"}
    source_id = "project:configs/llm/models/openai.toml"
    model_path = project_root / "configs" / "llm" / "models" / "openai.toml"

    overrides = client.patch(
        "/v2/config",
        headers=headers,
        json={
            "operations": [
                {
                    "source_id": source_id,
                    "path": "llm.models.gpt_5_5.request_overrides.temperature",
                    "op": "set",
                    "value": 0.4,
                }
            ]
        },
    )
    assert overrides.status_code == 200

    switched = client.patch(
        "/v2/config",
        headers=headers,
        json={
            "operations": [
                {
                    "source_id": source_id,
                    "path": "llm.models.gpt_5_5.providers",
                    "op": "set",
                    "value": [
                        {"provider": "openai_proxy", "provider_model": "gpt-5.5"}
                    ],
                }
            ]
        },
    )
    assert switched.status_code == 200
    reloaded = client.post("/v2/config/reload", headers=headers)
    assert reloaded.status_code == 200
    switched_generation = reloaded.json()["generation_id"]
    switched_source = model_path.read_text(encoding="utf-8")
    assert 'provider = "openai_proxy"' in switched_source
    assert "[llm.models.gpt_5_5.adapter_options]" in switched_source
    assert 'reasoning_keep = "encrypted"' in switched_source
    assert "[llm.models.gpt_5_5.request_overrides]" in switched_source
    assert "temperature = 0.4" in switched_source

    incompatible = client.patch(
        "/v2/config",
        headers=headers,
        json={
            "operations": [
                {
                    "source_id": source_id,
                    "path": "llm.models.gpt_5_5.providers",
                    "op": "set",
                    "value": [{"provider": "kimi", "provider_model": "gpt-5.5"}],
                }
            ]
        },
    )

    assert incompatible.status_code == 422
    assert incompatible.json()["error"]["code"] == "config.invalid"
    assert model_path.read_text(encoding="utf-8") == switched_source
    runtime = (await endpoint.configuration.status())["runtime"]
    assert isinstance(runtime, dict)
    assert runtime["generation_id"] == switched_generation


async def test_agent_workspace_mutation_reaches_endpoint_event_stream(
    tmp_path: Path,
) -> None:
    note = tmp_path / "runtime" / "workspace" / "note.md"
    note.parent.mkdir(parents=True)
    note.write_text("old text", encoding="utf-8")
    app = (
        await AgentBuilder(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_agent_settings(AgentSettings(interactive=False))
        .with_loop_settings(LoopSettings(user=TurnSettings(max_cycles=2)))
        .with_llm_runner(
            FakeLLM(
                (
                    _tool_result(
                        ToolCallRecord(
                            id="select_workspace",
                            name="select_action_domains",
                            arguments={"domains": ["workspace"]},
                            kind=ToolKind.CONTROL,
                        )
                    ),
                    _tool_result(
                        ToolCallRecord(
                            id="patch_note",
                            name="workspace.edit",
                            arguments={
                                "target_link": "workspace:note.md",
                                "edits": [
                                    {"old_text": "old text", "new_text": "new text"}
                                ],
                            },
                            kind=ToolKind.ACTION,
                        )
                    ),
                    _tool_result(
                        ToolCallRecord(
                            id="select_core",
                            name="select_action_domains",
                            arguments={"domains": ["core"]},
                            kind=ToolKind.CONTROL,
                        )
                    ),
                    _tool_result(
                        ToolCallRecord(
                            id="answer",
                            name="core.answer",
                            arguments={"guide_blocks": [{"text": "done"}]},
                            kind=ToolKind.ACTION,
                        )
                    ),
                    _json_result({"text": "done"}),
                )
            )
        )
        .build()
    )
    endpoint = mount_endpoint(app, EndpointSettings(token="x" * 32))

    outcome = await _run_once(app, "update the note")

    assert outcome.answered is True
    assert note.read_text(encoding="utf-8") == "new text"
    page = endpoint.events.replay(
        after=0,
        mode=ObservationLevel.NORMAL,
        limit=200,
    )
    changes = [
        event
        for event in page.events
        if event.name == "workspace.changed" and event.payload["operation"] == "edit"
    ]
    assert len(changes) == 1
    assert changes[0].source == "workspace.engine"
    assert changes[0].payload["links"] == ["workspace:note.md"]


async def test_agent_builder_run_once_answers_with_real_action_and_context(
    tmp_path: Path,
) -> None:
    recorder = _CompletionRecorder()
    app = (
        await AgentBuilder(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_agent_settings(AgentSettings(interactive=False))
        .with_loop_settings(LoopSettings(user=TurnSettings(max_cycles=2)))
        .with_user_turn_completion_handler(recorder)
        .with_llm_runner(
            FakeLLM(
                (
                    _tool_result(
                        ToolCallRecord(
                            id="select_1",
                            name="select_action_domains",
                            arguments={"domains": ["core"]},
                            kind=ToolKind.CONTROL,
                        )
                    ),
                    _tool_result(
                        ToolCallRecord(
                            id="answer_1",
                            name="core.answer",
                            arguments={"guide_blocks": [{"text": "answer"}]},
                            kind=ToolKind.ACTION,
                        )
                    ),
                    _json_result({"text": "done"}),
                )
            )
        )
        .build()
    )

    outcome = await _run_once(app, "please answer")

    assert outcome.answered is True
    assert outcome.context_completion is not None
    assert len(outcome.context_completion.trace.entries) == 2
    assert outcome.context_completion.inputs[0].text == "please answer"
    assert len(recorder.completions) == 1
    assert recorder.completions[0].output is not None
    assert recorder.completions[0].output.text == "done"


async def test_agent_builder_runs_resource_conversion_through_real_action_chain(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "runtime" / "workspace"
    source = workspace_root / "incoming" / "blank.pdf"
    source.parent.mkdir(parents=True)
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with source.open("wb") as handle:
        writer.write(handle)
    app = (
        await AgentBuilder(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_agent_settings(AgentSettings(interactive=False))
        .with_loop_settings(LoopSettings(user=TurnSettings(max_cycles=2)))
        .with_llm_runner(
            FakeLLM(
                (
                    _tool_result(
                        ToolCallRecord(
                            id="select_workspace",
                            name="select_action_domains",
                            arguments={"domains": ["workspace"]},
                            kind=ToolKind.CONTROL,
                        )
                    ),
                    _tool_result(
                        ToolCallRecord(
                            id="convert_1",
                            name="workspace.convert_with_pypdf",
                            arguments={
                                "source_link": "workspace:incoming/blank.pdf",
                                "target_link": "workspace:converted/blank.md",
                            },
                            kind=ToolKind.ACTION,
                        )
                    ),
                    _tool_result(
                        ToolCallRecord(
                            id="select_core",
                            name="select_action_domains",
                            arguments={"domains": ["core"]},
                            kind=ToolKind.CONTROL,
                        )
                    ),
                    _tool_result(
                        ToolCallRecord(
                            id="answer_1",
                            name="core.answer",
                            arguments={"guide_blocks": [{"text": "answer"}]},
                            kind=ToolKind.ACTION,
                        )
                    ),
                    _json_result({"text": "converted"}),
                )
            )
        )
        .build()
    )

    outcome = await _run_once(app, "convert the PDF")

    assert outcome.answered is True
    markdown = workspace_root / "converted" / "blank.md"
    page = workspace_root / "converted" / "blank.assets" / "page-001.png"
    assert markdown.is_file()
    assert "workspace:converted/blank.assets/page-001.png" in markdown.read_text(
        encoding="utf-8"
    )
    assert page.is_file()


async def test_agent_builder_cycle_limit_suspends_until_explicit_decision(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "doc.md").write_text("hello", encoding="utf-8")
    config = _test_config(
        tmp_path,
        {"workspace.root": str(workspace_root)},
    )
    app = (
        await AgentBuilder(root=tmp_path)
        .with_config_environment(config)
        .with_agent_settings(AgentSettings(interactive=False))
        .with_loop_settings(LoopSettings(user=TurnSettings(max_cycles=1)))
        .with_llm_runner(
            FakeLLM(
                (
                    _tool_result(
                        ToolCallRecord(
                            id="select_1",
                            name="select_action_domains",
                            arguments={"domains": ["workspace"]},
                            kind=ToolKind.CONTROL,
                        )
                    ),
                    _tool_result(
                        ToolCallRecord(
                            id="scan_1",
                            name="workspace.list",
                            arguments={},
                            kind=ToolKind.ACTION,
                        )
                    ),
                )
            )
        )
        .build()
    )

    from tinysoul.agent import UserTurnRequest
    from tinysoul.kernel.loop.interaction.inbox import WaitReason

    await app.agent_runner.prepare()
    handle = await app.commands.submit_turn(UserTurnRequest("scan only"))
    running = asyncio.create_task(app.agent_runner.run())
    try:
        async with asyncio.timeout(3):
            while handle.wait_reason is not WaitReason.BUDGET:
                assert not handle.done
                await asyncio.sleep(0.01)
        assert handle.budget_request is not None
        assert handle.budget_request.next_cycle_index == 2
        await app.commands.cancel_turn(handle.turn_id)
        assert (await handle.wait()).outcome is not None
    finally:
        running.cancel()
        try:
            await running
        except asyncio.CancelledError:
            pass
        await app.close()


async def test_agent_runner_idle_exit_ends_program(tmp_path: Path) -> None:
    app = (
        await AgentBuilder(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_agent_settings(AgentSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
        .build()
    )

    await app.submit_input("exit")
    outcome = await app.run()

    assert outcome.turns == ()
    assert outcome.transfer is not None
    assert outcome.transfer.action is RuntimeTransferAction.END
    assert outcome.transfer.target.level is RunLevel.AGENT


async def test_turn_runner_ignores_stop_control_without_turn_scope(
    tmp_path: Path,
) -> None:
    bus = SignalBus()
    llm = FakeLLM(
        (
            _tool_result(
                ToolCallRecord(
                    id="select_1",
                    name="select_action_domains",
                    arguments={"domains": ["core"]},
                    kind=ToolKind.CONTROL,
                )
            ),
            _tool_result(
                ToolCallRecord(
                    id="answer_1",
                    name="core.answer",
                    arguments={"guide_blocks": [{"text": "answer"}]},
                    kind=ToolKind.ACTION,
                )
            ),
            _json_result({"text": "done"}),
        )
    )
    app = (
        await AgentBuilder(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_agent_settings(AgentSettings(interactive=False))
        .with_signal_bus(bus)
        .with_llm_runner(llm)
        .build()
    )
    bus.emit(
        build_control_request_signal(
            LoopControlKind.STOP_TURN,
            scope=app.agent_runner.scope,
            source="test",
            text="stop",
        )
    )

    outcome = await _run_once(app, "please stop")

    assert outcome.answered is True
    assert outcome.transfer is None
    assert outcome.context_completion is not None
    assert len(llm.calls) == 3


async def test_agent_builder_missing_agent_is_context_startup_failure(
    tmp_path: Path,
) -> None:
    config = _test_config(
        tmp_path,
        {"home.root": str(tmp_path / "missing_home")},
    )

    with pytest.raises(RuntimeException) as raised:
        (
            await AgentBuilder(root=tmp_path)
            .with_config_environment(config)
            .with_agent_settings(AgentSettings(interactive=False))
            .with_llm_runner(FakeLLM(()))
            .build()
        )

    exc = raised.value
    assert exc.reason == RUNTIME_STARTUP_FAILED
    assert exc.payload["module"] == "home"


@pytest.mark.parametrize(
    ("overrides", "module", "key", "kind"),
    (
        ({"home.max_read_chars": 0}, "home", "home.max_read_chars", None),
        (
            {"infra.embedding.batch_size": 0},
            "agent",
            "infra.embedding.batch_size",
            "agent.configuration_failed",
        ),
        (
            {"workspace.max_files": 0},
            "workspace",
            "workspace.max_files",
            None,
        ),
        (
            {"execution.max_source_chars": 0},
            "execution",
            "execution.max_source_chars",
            "execution.configuration_failed",
        ),
        (
            {
                "execution.enabled": True,
                "execution.interpreters.python.executable": "tinysoul-missing-interpreter",
            },
            "execution",
            "execution.interpreters.python.executable",
            "execution.configuration_failed",
        ),
        (
            {"jobs.retained_capacity": 0},
            "jobs",
            "jobs.retained_capacity",
            "jobs.configuration_failed",
        ),
        (
            {"loop.max_cycles_per_turn": 0},
            "loop",
            "loop.max_cycles_per_turn",
            None,
        ),
        (
            {"loop.cycle.phase1_task_profile": "missing_profile"},
            "loop",
            "loop.cycle.phase1_task_profile",
            None,
        ),
    ),
    ids=(
        "home-config",
        "infra-config",
        "workspace-config",
        "execution-config",
        "execution-dependency",
        "jobs-config",
        "loop-config",
        "loop-task-profile",
    ),
)
async def test_agent_builder_maps_owned_startup_failure(
    tmp_path: Path,
    overrides: dict[str, object],
    module: str,
    key: str,
    kind: str | None,
) -> None:
    config = _test_config(tmp_path, overrides)

    with pytest.raises(RuntimeException) as raised:
        (
            await AgentBuilder(root=tmp_path)
            .with_config_environment(config)
            .with_agent_settings(AgentSettings(interactive=False))
            .with_llm_runner(FakeLLM(()))
            .build()
        )

    exc = raised.value
    assert exc.reason == RUNTIME_STARTUP_FAILED
    assert exc.payload["module"] == module
    assert exc.payload["key"] == key
    if kind is not None:
        assert exc.payload["kind"] == kind


async def test_agent_builder_corrupt_manifest_is_workspace_startup_failure(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    manifest_path = workspace_root / ".tinysoul" / "workspace_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("not-json", encoding="utf-8")
    config = _test_config(
        tmp_path,
        {"workspace.root": str(workspace_root)},
    )

    with pytest.raises(RuntimeException) as raised:
        (
            await AgentBuilder(root=tmp_path)
            .with_config_environment(config)
            .with_agent_settings(AgentSettings(interactive=False))
            .with_llm_runner(FakeLLM(()))
            .build()
        )

    assert raised.value.reason == RUNTIME_STARTUP_FAILED
    assert raised.value.payload["module"] == "workspace"


async def test_agent_builder_does_not_map_programming_errors_to_startup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = (
        AgentBuilder(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_agent_settings(AgentSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
    )

    def explode(*args, **kwargs):
        raise RuntimeError("programming error")

    monkeypatch.setattr(builder, "_build_workspace", explode)

    with pytest.raises(RuntimeError, match="programming error"):
        await builder.build()


async def test_agent_builder_agent_config_error_is_agent_startup_failure(
    tmp_path: Path,
) -> None:
    config = _test_config(tmp_path, {"agent.interactive": "bad"})

    with pytest.raises(RuntimeException) as raised:
        (
            await AgentBuilder(root=tmp_path)
            .with_config_environment(config)
            .with_loop_settings(LoopSettings())
            .with_llm_runner(FakeLLM(()))
            .build()
        )

    exc = raised.value
    assert exc.reason == RUNTIME_STARTUP_FAILED
    assert exc.payload["module"] == "agent"
    assert exc.payload["key"] == "agent.interactive"


async def test_agent_builder_llm_config_error_is_llm_startup_failure(
    tmp_path: Path,
) -> None:
    config = _test_config(tmp_path, {"llm.tasks.framework.models": ["missing_model"]})

    with pytest.raises(RuntimeException) as raised:
        (
            await AgentBuilder(root=tmp_path)
            .with_config_environment(config)
            .with_agent_settings(AgentSettings(interactive=False))
            .with_loop_settings(LoopSettings())
            .build()
        )

    exc = raised.value
    assert exc.reason == RUNTIME_STARTUP_FAILED
    assert exc.payload["module"] == "llm"
    assert exc.payload["key"] == "llm.tasks.framework.models"


def _action_catalog_item(
    client: TestClient,
    headers: dict[str, str],
    action_id: str,
) -> JsonObject:
    response = client.get("/v2/config/actions", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, dict)
    actions = payload.get("actions")
    assert isinstance(actions, list)
    for item in actions:
        if isinstance(item, dict) and item.get("id") == action_id:
            return to_json_object(item)
    raise AssertionError(f"Missing Action catalog entry: {action_id}")


async def test_generation_closes_owned_llm_on_build_failure_and_never_closes_borrowed(
    tmp_path: Path, monkeypatch
) -> None:
    closed: list[str] = []

    class OwnedLLM(FakeLLM):
        async def close(self):
            closed.append("owned")
            return ()

    owned = OwnedLLM(())

    async def build_llm(*args, **kwargs):
        return owned

    failure = RuntimeError("home construction failed")

    def build_home(*args, **kwargs):
        raise failure

    config = _test_config(tmp_path)
    builder = AgentBuilder(tmp_path).with_config_environment(config)
    monkeypatch.setattr(builder, "_build_llm", build_llm)
    monkeypatch.setattr(builder, "_build_home", build_home)
    with pytest.raises(RuntimeError) as caught:
        await builder.build()
    assert caught.value is failure
    assert closed == ["owned"]

    borrowed = OwnedLLM(())
    app = (
        await AgentBuilder(tmp_path)
        .with_config_environment(config)
        .with_llm_runner(borrowed)
        .build()
    )
    assert await app.close() == ()
    assert closed == ["owned"]


def _json_object(value: object) -> JsonObject:
    assert isinstance(value, dict)
    return to_json_object(value)


def _tool_result(*tool_calls: ToolCallRecord) -> TaskResult:
    return TaskResult.success(
        raw_response=RawResponse(
            answer_text="",
            model_id="fake",
            provider_id="fake",
            tool_calls=tool_calls,
        ),
        answer=None,
        tool_calls=tool_calls,
    )


def _json_result(value: JsonObject) -> TaskResult:
    return TaskResult.success(
        raw_response=RawResponse(
            answer_text="{}",
            model_id="fake",
            provider_id="fake",
        ),
        answer=JsonAnswer(value),
        tool_calls=(),
    )


def _test_config(
    tmp_path: Path,
    overrides: dict[str, object] | None = None,
) -> ConfigEnvironment:
    project_root = tmp_path / ".config-project"
    copy_initialized_project(project_root)
    home_root = tmp_path / "home"
    agent_path = home_root / "agent" / "AGENT.md"
    agent_path.parent.mkdir(parents=True, exist_ok=True)
    agent_path.write_text("# Test Agent\n", encoding="utf-8")
    values: dict[str, object] = {
        "agent.interactive": False,
        "home.root": str(home_root),
        "home.runtime_root": str(tmp_path / "runtime" / "home"),
        "memory.root": str(tmp_path / "memory"),
        "session.root": str(tmp_path / "runtime" / "session"),
        "workspace.root": str(tmp_path / "runtime" / "workspace"),
        "reflection.archive_root": str(tmp_path / "archive"),
    }
    if overrides is not None:
        values.update(overrides)
    return ConfigEnvironment.from_project_root(root=project_root, overrides=values)


async def _run_once(app: AgentAssembly, text: str) -> TurnOutcome:
    """Exercise the real queue/Inbox path without starting mounted HTTP hosts."""
    from tinysoul.agent import UserTurnRequest

    await app.agent_runner.prepare()
    await app.generation_handle.snapshot().generation.sources.start(
        app.commands.publish_internal
    )
    handle = await app.commands.submit_turn(UserTurnRequest(text))
    running = asyncio.create_task(app.agent_runner.run())
    try:
        result = await asyncio.wait_for(handle.wait(), 10)
        assert isinstance(result.outcome, TurnOutcome)
        return result.outcome
    finally:
        running.cancel()
        try:
            await running
        except asyncio.CancelledError:
            pass
        await app.agent_runner.close_requests()
        await app.close()
