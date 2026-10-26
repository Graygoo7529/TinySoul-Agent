from __future__ import annotations
import asyncio
from pathlib import Path
from time import monotonic
import httpx
import pytest
from fastapi.testclient import TestClient
from tests.support.project import create_test_project
from tinysoul.agent.composition.assembly import AgentRuntime
from tinysoul.agent.composition.builder import standard_agent
from tinysoul.agent.config import AgentSettings
from tinysoul.gateway.endpoint import EndpointSettings
from tinysoul.gateway.endpoint.host import mount_endpoint
from tinysoul.gateway.endpoint.http import create_endpoint_app
from tinysoul.infra.config import ConfigEnvironment
from tinysoul.infra.json import to_json_object
from tinysoul.kernel.loop import LoopSettings, TurnSettings
from tinysoul.llm.failures import LLMFailureKind
from tinysoul.llm.protocol.tools import ToolCallRecord, ToolKind
from tinysoul.runtime import RUNTIME_STARTUP_FAILED, ObservationLevel, RuntimeException
from tests.agent.composition.support import (
    FakeLLM,
    _action_catalog_item,
    _json_object,
    _json_result,
    _run_once,
    _test_config,
    _tool_result,
    endpoint_runtimes as endpoint_runtimes,
)

pytestmark = pytest.mark.integration


async def test_agent_builder_mounts_endpoint_as_service_and_model_output_source(
    tmp_path: Path,
) -> None:
    app = (
        await standard_agent(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_agent_settings(AgentSettings(interactive=True))
        .with_llm_runner(FakeLLM(()))
        .build()
        .build_runtime()
    )
    endpoint = mount_endpoint(app, EndpointSettings(token="x" * 32))
    entered, release = asyncio.Event(), asyncio.Event()

    class ActivationGate:
        async def start(self) -> None:
            entered.set()
            await release.wait()

        async def stop(self) -> None:
            pass

    assert app.input_sources == () and len(app.host_services) == 1
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


async def test_provider_activation_requires_credentials_and_accepts_configured_key(
    tmp_path: Path,
    endpoint_runtimes: list[AgentRuntime],
) -> None:
    project_root = tmp_path / "project"
    create_test_project(project_root)
    app = (
        await standard_agent(root=project_root)
        .with_config_environment(
            ConfigEnvironment.from_project_root(project_root, env={})
        )
        .with_agent_settings(AgentSettings(interactive=False))
        .build()
        .build_runtime()
    )
    endpoint = mount_endpoint(app, EndpointSettings(token="x" * 32))
    endpoint_runtimes.append(app)
    await app.activate()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=create_endpoint_app(endpoint, endpoint.settings)
        ),
        base_url="http://test",
    ) as client:
        headers = {"Authorization": f"Bearer {'x' * 32}"}

        runtime_before = _json_object(
            (await client.get("/v2/config", headers=headers)).json()["runtime"]
        )
        llm_status = _json_object(runtime_before["llm"])
        providers = llm_status["providers"]
        assert isinstance(providers, list)
        test = next(
            item
            for item in providers
            if isinstance(item, dict) and item.get("id") == "test"
        )
        assert test == {
            "id": "test",
            "credential_state": "missing",
            "api_key_envs": ["TEST_LLM_API_KEY"],
        }

        response = await client.patch(
            "/v2/config",
            headers=headers,
            json={
                "operations": [
                    {
                        "source_id": "project:configs/llm/providers.toml",
                        "path": "llm.providers.test.enabled",
                        "op": "set",
                        "value": True,
                    }
                ]
            },
        )

        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "config.invalid"
        assert "TEST_LLM_API_KEY" in error["message"]
        assert error["details"]["key"] == "llm.providers.test.api_key_envs"
        runtime_after = (await client.get("/v2/config", headers=headers)).json()[
            "runtime"
        ]
        assert runtime_after["generation_id"] == runtime_before["generation_id"]
        providers_path = project_root / "configs" / "llm" / "providers.toml"
        assert "enabled = true" not in providers_path.read_text(encoding="utf-8")

        credential_response = await client.patch(
            "/v2/config",
            headers=headers,
            json={
                "operations": [
                    {
                        "source_id": "dotenv",
                        "path": "TEST_LLM_API_KEY",
                        "op": "set",
                        "value": "configured",
                    }
                ]
            },
        )
        assert credential_response.status_code == 200
        assert (
            await client.post("/v2/config/reload", headers=headers)
        ).status_code == 200
        configured_runtime = (await client.get("/v2/config", headers=headers)).json()[
            "runtime"
        ]
        configured_llm = _json_object(configured_runtime["llm"])
        configured_providers = configured_llm["providers"]
        assert isinstance(configured_providers, list)
        assert (
            next(
                item
                for item in configured_providers
                if isinstance(item, dict) and item.get("id") == "test"
            )["credential_state"]
            == "configured"
        )

        enabled_response = await client.patch(
            "/v2/config",
            headers=headers,
            json={
                "operations": [
                    {
                        "source_id": "project:configs/llm/providers.toml",
                        "path": "llm.providers.test.enabled",
                        "op": "set",
                        "value": True,
                    }
                ]
            },
        )
        assert enabled_response.status_code == 200
        assert "enabled = true" in providers_path.read_text(encoding="utf-8")


async def test_enabled_provider_requires_credentials_on_startup(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "development-project"
    create_test_project(project_root)
    providers = project_root / "configs" / "llm" / "providers.toml"
    providers.write_text(
        providers.read_text(encoding="utf-8").replace(
            "enabled = false", "enabled = true"
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeException) as error:
        (
            await standard_agent(root=project_root)
            .with_config_environment(
                ConfigEnvironment.from_project_root(project_root, env={})
            )
            .with_agent_settings(AgentSettings(interactive=False))
            .build()
            .build_runtime()
        )

    assert error.value.reason == RUNTIME_STARTUP_FAILED
    assert error.value.payload["kind"] == LLMFailureKind.CONFIGURATION_FAILED


async def test_endpoint_config_reload_rebuilds_generation_and_keeps_event_buffer(
    tmp_path: Path,
    endpoint_runtimes: list[AgentRuntime],
) -> None:
    project_root = tmp_path / "project"
    create_test_project(project_root)
    app = (
        await standard_agent(root=project_root)
        .with_config_environment(
            ConfigEnvironment.from_project_root(project_root, env={})
        )
        .with_agent_settings(AgentSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
        .build()
        .build_runtime()
    )
    endpoint = mount_endpoint(
        app,
        EndpointSettings(
            token="x" * 32,
            websocket_heartbeat_seconds=0.05,
        ),
    )
    endpoint_runtimes.append(app)
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
                        "source_id": "project-document:action.catalog:configs/action/catalog/workspace/actions/analyze.toml",
                        "path": "runtime.timeout_seconds",
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
        and item["execution"]["executor"] == "workspace.analyze"
        and item["model_uses"]
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
        project_root
        / "configs"
        / "action"
        / "catalog"
        / "workspace"
        / "actions"
        / "analyze.toml"
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


async def test_endpoint_reload_activates_saved_action_configuration(
    tmp_path: Path,
    endpoint_runtimes: list[AgentRuntime],
) -> None:
    project_root = create_test_project(tmp_path / "project")
    app = await (
        standard_agent(root=project_root)
        .with_config_environment(
            ConfigEnvironment.from_project_root(project_root, env={})
        )
        .with_agent_settings(AgentSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
        .build()
        .build_runtime()
    )
    endpoint = mount_endpoint(app, EndpointSettings(token="x" * 32))
    endpoint_runtimes.append(app)
    await app.activate()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=create_endpoint_app(endpoint, endpoint.settings)
        ),
        base_url="http://test",
    ) as client:
        headers = {"Authorization": f"Bearer {'x' * 32}"}
        before = await _action_catalog_item(client, headers, "workspace.read")
        saved = await client.patch(
            "/v2/config",
            headers=headers,
            json={
                "operations": [
                    {
                        "source_id": "project-document:action.catalog:configs/action/catalog/workspace/actions/read.toml",
                        "path": "visibility.default",
                        "op": "set",
                        "value": False,
                    },
                    {
                        "source_id": "project-document:action.catalog:configs/action/catalog/workspace/actions/read.toml",
                        "path": "runtime.timeout_seconds",
                        "op": "set",
                        "value": 19,
                    },
                ]
            },
        )
        assert saved.status_code == 200
        assert await _action_catalog_item(client, headers, "workspace.read") == before
        reloaded = await client.post("/v2/config/reload", headers=headers)
        assert reloaded.status_code == 200
        after = await _action_catalog_item(client, headers, "workspace.read")
        assert after["supported"] is True and after["available"] is False
        assert _json_object(after["selection"])["source"] == "action.visibility.default"
        assert _json_object(after["runtime"])["timeout_seconds"] == 19


async def test_endpoint_provider_switch_preserves_model_options_and_rolls_back_incompatible_adapter(
    tmp_path: Path,
    endpoint_runtimes: list[AgentRuntime],
) -> None:
    project_root = tmp_path / "project"
    create_test_project(project_root)
    providers_path = project_root / "configs" / "llm" / "providers.toml"
    with providers_path.open("a", encoding="utf-8") as providers:
        providers.write(
            "\n[llm.providers.openai-proxy]\n"
            "enabled = false\n"
            'api_key_envs = ["OPENAI_PROXY_API_KEY"]\n'
            "[llm.providers.openai-proxy.endpoints.openai-responses]\n"
            'base_url = "https://proxy.example/v1"\n'
            "[llm.providers.test.endpoints.openai-responses]\n"
            'base_url = "https://test.example/v1"\n'
            "[llm.providers.chat-only]\nenabled = false\n"
            'api_key_envs = ["CHAT_ONLY_KEY"]\n'
            "[llm.providers.chat-only.endpoints.openai-chat]\n"
            'base_url = "https://chat.example/v1"\n'
        )
    model_file = project_root / "configs" / "llm" / "models" / "test.toml"
    model_file.write_text(
        model_file.read_text(encoding="utf-8").replace(
            'adapter = "openai-chat"', 'adapter = "openai-responses"'
        )
        + '\n[llm.models.test.adapter_options]\nnative_replay = "encrypted"\n',
        encoding="utf-8",
    )
    app = (
        await standard_agent(root=project_root)
        .with_config_environment(
            ConfigEnvironment.from_project_root(project_root, env={})
        )
        .with_agent_settings(AgentSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
        .build()
        .build_runtime()
    )
    endpoint = mount_endpoint(app, EndpointSettings(token="x" * 32))
    endpoint_runtimes.append(app)
    await app.activate()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=create_endpoint_app(endpoint, endpoint.settings)
        ),
        base_url="http://test",
    ) as client:
        headers = {"Authorization": f"Bearer {'x' * 32}"}
        source_id = "project:configs/llm/models/test.toml"
        model_path = project_root / "configs" / "llm" / "models" / "test.toml"

        overrides = await client.patch(
            "/v2/config",
            headers=headers,
            json={
                "operations": [
                    {
                        "source_id": source_id,
                        "path": "llm.models.test.request_overrides.temperature",
                        "op": "set",
                        "value": 0.4,
                    }
                ]
            },
        )
        assert overrides.status_code == 200

        switched = await client.patch(
            "/v2/config",
            headers=headers,
            json={
                "operations": [
                    {
                        "source_id": source_id,
                        "path": "llm.models.test.providers",
                        "op": "set",
                        "value": [
                            {
                                "provider": "openai-proxy",
                                "provider_model": "remote-test",
                            }
                        ],
                    }
                ]
            },
        )
        assert switched.status_code == 200
        reloaded = await client.post("/v2/config/reload", headers=headers)
        assert reloaded.status_code == 200
        switched_generation = reloaded.json()["generation_id"]
        switched_source = model_path.read_text(encoding="utf-8")
        assert 'provider = "openai-proxy"' in switched_source
        assert "[llm.models.test.adapter_options]" in switched_source
        assert 'native_replay = "encrypted"' in switched_source
        assert "[llm.models.test.request_overrides]" in switched_source
        assert "temperature = 0.4" in switched_source

        incompatible = await client.patch(
            "/v2/config",
            headers=headers,
            json={
                "operations": [
                    {
                        "source_id": source_id,
                        "path": "llm.models.test.providers",
                        "op": "set",
                        "value": [
                            {"provider": "chat-only", "provider_model": "remote-test"}
                        ],
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
        await standard_agent(root=tmp_path)
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
                                "target_ref": "workspace:note.md",
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
        .build_runtime()
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
    assert changes[0].payload["refs"] == ["workspace:note.md"]
