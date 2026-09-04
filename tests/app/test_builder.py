from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from pypdf import PdfWriter

from tinysoul.app import AppSettings, TinySoulAppBuilder
from tinysoul.endpoint import EndpointSettings
from tinysoul.endpoint.http import create_endpoint_app
from tinysoul.infra.config import ConfigEnvironment, ConfigMutation
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.llm.requests import TaskCall
from tinysoul.llm.responses import JsonAnswer, RawResponse, TaskResult
from tinysoul.llm.tools import ToolCallRecord, ToolKind
from tinysoul.loop import (
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


class FakeLLM:
    def __init__(self, results: tuple[TaskResult, ...]) -> None:
        self.results = deque(results)
        self.calls: list[TaskCall] = []

    def run(self, call: TaskCall) -> TaskResult:
        self.calls.append(call)
        return self.results.popleft()


@dataclass
class _CompletionRecorder:
    completions: list[TurnCompletion] = field(default_factory=list)

    def handle(self, completion: TurnCompletion) -> None:
        self.completions.append(completion)


def test_app_test_config_isolates_all_mutable_roots(tmp_path: Path) -> None:
    config = _test_config(tmp_path)

    home = config.section_tree("home")
    memory = config.section_tree("memory")
    session = config.section_tree("session")
    workspace = config.section_tree("workspace")
    maintenance = config.section_tree("maintenance")

    assert home["root"] == str(tmp_path / "home")
    assert home["runtime_root"] == str(tmp_path / "runtime" / "home")
    assert memory["root"] == str(tmp_path / "memory")
    assert session["root"] == str(tmp_path / "runtime" / "session")
    assert workspace["root"] == str(tmp_path / "runtime" / "workspace")
    assert maintenance["archive_root"] == str(tmp_path / "archive")
    assert maintenance["runtime_root"] == str(tmp_path / "runtime" / "maintenance")


def test_app_builder_cleans_project_capability_staging_on_startup(
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
        TinySoulAppBuilder(root=tmp_path)
        .with_config_environment(config)
        .with_app_settings(AppSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
        .build()
    )

    staging = tmp_path / "runtime" / ".staging"
    assert staging.is_dir()
    assert tuple(staging.iterdir()) == ()


def test_app_builder_mounts_endpoint_as_service_and_model_output_source(
    tmp_path: Path,
) -> None:
    app = (
        TinySoulAppBuilder(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_app_settings(AppSettings(interactive=True))
        .with_llm_runner(FakeLLM(()))
        .with_endpoint(EndpointSettings(token="x" * 32))
        .build()
    )

    assert app.endpoint is not None
    assert app.input_sources == ()
    assert len(app.services) == 1
    assert app.observations.mode.value == "model"


def test_endpoint_config_patch_rebuilds_generation_and_keeps_event_buffer(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    copy_initialized_project(project_root)
    app = (
        TinySoulAppBuilder(root=project_root)
        .with_config_environment(ConfigEnvironment.from_project_root(project_root))
        .with_app_settings(AppSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
        .with_endpoint(
            EndpointSettings(
                token="x" * 32,
                websocket_heartbeat_seconds=0.05,
            )
        )
        .build()
    )
    assert app.endpoint is not None
    endpoint = app.endpoint
    events = endpoint.events
    before = endpoint.configuration.status()["runtime"]
    after_sequence = events.latest_sequence

    client = TestClient(create_endpoint_app(endpoint, endpoint.settings))
    with client.websocket_connect("/v1/events/ws") as websocket:
        def receive_event_names() -> tuple[str, ...]:
            for _ in range(20):
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
            "/v1/config",
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
                        "path": "runtime.enabled",
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
                    {
                        "source_id": (
                            "project-document:action.catalog:configs/action/catalog/"
                            "execution/actions/wait.toml"
                        ),
                        "path": "tool.schema.properties.wait_seconds.default",
                        "op": "set",
                        "value": 20,
                    },
                ]
            },
        )
        assert response.status_code == 200
        result = response.json()
        assert isinstance(result, dict)
        websocket_event_names = receive_event_names()
        websocket_completed_names = receive_event_names()

    after = endpoint.configuration.status()["runtime"]
    action_catalog = client.get(
        "/v1/config/actions",
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
        and item["runtime"]["enabled"] is False
        and item["runtime"]["enabled_source"] == "action"
        and item["supported"] is True
        and item["available"] is False
        and "runtime.enabled" in item["source"]["editable_paths"]
        and item["source"]["document_kind"] == "action"
        for item in action_catalog.json()["actions"]
    )
    assert any(
        item["id"] == "web.search_by_kimi" and item["available"] is False
        for item in action_catalog.json()["actions"]
    )
    assert any(
        item["id"] == "execution.wait"
        and item["tool"]["schema"]["properties"]["wait_seconds"]["default"] == 20
        and "tool.schema.properties.wait_seconds.default"
        in item["source"]["editable_paths"]
        for item in action_catalog.json()["actions"]
    )
    assert any(
        item["id"] == "workspace"
        and item["source"]["document_kind"] == "domain"
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
    assert "enabled = false" in (
        project_root
        / "configs"
        / "action"
        / "catalog"
        / "workspace"
        / "actions"
        / "read.toml"
    ).read_text(encoding="utf-8")
    assert "default = 20" in (
        project_root
        / "configs"
        / "action"
        / "catalog"
        / "execution"
        / "actions"
        / "wait.toml"
    ).read_text(encoding="utf-8")
    invalid = client.patch(
        "/v1/config",
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
        "/v1/config",
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
    current_runtime = endpoint.configuration.status()["runtime"]
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
    assert [event.name for event in activation_events.events] == [
        "config.activation.started",
        "config.activation.completed",
        "config.activation.started",
        "config.activation.failed",
        "config.activation.started",
        "config.activation.failed",
    ]
    assert websocket_event_names == ("config.activation.started",)
    assert websocket_completed_names == ("config.activation.completed",)


def test_endpoint_action_activation_inherits_and_restores_runtime_policy(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    copy_initialized_project(project_root)
    app = (
        TinySoulAppBuilder(root=project_root)
        .with_config_environment(ConfigEnvironment.from_project_root(project_root))
        .with_app_settings(AppSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
        .with_endpoint(EndpointSettings(token="x" * 32))
        .build()
    )
    assert app.endpoint is not None
    endpoint = app.endpoint
    client = TestClient(create_endpoint_app(endpoint, endpoint.settings))
    headers = {"Authorization": f"Bearer {'x' * 32}"}
    domain_source = (
        "project-document:action.catalog:"
        "configs/action/catalog/workspace/domain.toml"
    )
    action_source = (
        "project-document:action.catalog:"
        "configs/action/catalog/workspace/actions/read.toml"
    )
    domain_path = (
        project_root
        / "configs"
        / "action"
        / "catalog"
        / "workspace"
        / "domain.toml"
    )

    runtime_before = _json_object(endpoint.configuration.status()["runtime"])
    generation_before = runtime_before["generation_id"]
    invalid = client.patch(
        "/v1/config",
        headers=headers,
        json={
            "operations": [
                {
                    "source_id": domain_source,
                    "path": "runtime.enabled",
                    "op": "set",
                    "value": "false",
                }
            ]
        },
    )
    assert invalid.status_code == 422
    runtime_after_invalid = _json_object(endpoint.configuration.status()["runtime"])
    assert runtime_after_invalid["generation_id"] == generation_before
    assert "enabled = true" in domain_path.read_text(encoding="utf-8")

    routed = client.patch(
        "/v1/config",
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
        "/v1/config",
        headers=headers,
        json={
            "operations": [
                {
                    "source_id": domain_source,
                    "path": "runtime.enabled",
                    "op": "set",
                    "value": False,
                }
            ]
        },
    )
    assert domain_disabled.status_code == 200
    disabled_read = _action_catalog_item(client, headers, "workspace.read")
    disabled_analysis = _action_catalog_item(client, headers, "workspace.analyze")
    disabled_runtime = _json_object(disabled_read["runtime"])
    assert disabled_runtime["enabled"] is False
    assert disabled_runtime["enabled_source"] == "domain"
    assert disabled_read["supported"] is True
    assert disabled_read["available"] is False
    assert disabled_analysis["available"] is False
    assert "workspace.analyze" in (
        project_root / "configs" / "action" / "routing.toml"
    ).read_text(encoding="utf-8")

    action_enabled = client.patch(
        "/v1/config",
        headers=headers,
        json={
            "operations": [
                {
                    "source_id": action_source,
                    "path": "runtime.enabled",
                    "op": "set",
                    "value": True,
                }
            ]
        },
    )
    assert action_enabled.status_code == 200
    enabled_read = _action_catalog_item(client, headers, "workspace.read")
    enabled_runtime = _json_object(enabled_read["runtime"])
    assert enabled_runtime["enabled"] is True
    assert enabled_runtime["enabled_source"] == "action"
    assert enabled_read["available"] is True

    action_inherited = client.patch(
        "/v1/config",
        headers=headers,
        json={
            "operations": [
                {
                    "source_id": action_source,
                    "path": "runtime.enabled",
                    "op": "delete",
                }
            ]
        },
    )
    assert action_inherited.status_code == 200
    inherited_read = _action_catalog_item(client, headers, "workspace.read")
    inherited_runtime = _json_object(inherited_read["runtime"])
    assert inherited_runtime["enabled"] is False
    assert inherited_runtime["enabled_source"] == "domain"
    assert inherited_read["available"] is False

    domain_default = client.patch(
        "/v1/config",
        headers=headers,
        json={
            "operations": [
                {
                    "source_id": domain_source,
                    "path": "runtime.enabled",
                    "op": "delete",
                }
            ]
        },
    )
    assert domain_default.status_code == 200
    restored_read = _action_catalog_item(client, headers, "workspace.read")
    restored_analysis = _action_catalog_item(client, headers, "workspace.analyze")
    restored_runtime = _json_object(restored_read["runtime"])
    assert restored_runtime["enabled"] is True
    assert restored_runtime["enabled_source"] == "default"
    assert restored_read["available"] is True
    assert restored_analysis["available"] is True
    assert "enabled =" not in domain_path.read_text(encoding="utf-8")

    answer_disabled = client.patch(
        "/v1/config",
        headers=headers,
        json={
            "operations": [
                {
                    "source_id": (
                        "project-document:action.catalog:"
                        "configs/action/catalog/core/actions/answer.toml"
                    ),
                    "path": "runtime.enabled",
                    "op": "set",
                    "value": False,
                }
            ]
        },
    )
    assert answer_disabled.status_code == 200
    disabled_answer = _action_catalog_item(client, headers, "core.answer")
    disabled_answer_runtime = _json_object(disabled_answer["runtime"])
    assert disabled_answer_runtime["enabled"] is False
    assert disabled_answer["supported"] is True
    assert disabled_answer["available"] is False


def test_endpoint_provider_switch_preserves_model_options_and_rolls_back_incompatible_adapter(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    copy_initialized_project(project_root)
    providers_path = project_root / "configs" / "llm" / "providers.toml"
    with providers_path.open("a", encoding="utf-8") as providers:
        providers.write(
            "\n[llm.providers.openai_proxy]\n"
            "enabled = true\n"
            'adapter = "openai"\n'
            'api_style = "openai_responses"\n'
            'base_url = "https://proxy.example/v1"\n'
            'api_key_envs = ["OPENAI_PROXY_API_KEY"]\n'
        )
    app = (
        TinySoulAppBuilder(root=project_root)
        .with_config_environment(ConfigEnvironment.from_project_root(project_root))
        .with_app_settings(AppSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
        .with_endpoint(EndpointSettings(token="x" * 32))
        .build()
    )
    assert app.endpoint is not None
    endpoint = app.endpoint
    client = TestClient(create_endpoint_app(endpoint, endpoint.settings))
    headers = {"Authorization": f"Bearer {'x' * 32}"}
    source_id = "project:configs/llm/models/openai.toml"
    model_path = project_root / "configs" / "llm" / "models" / "openai.toml"

    overrides = client.patch(
        "/v1/config",
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
        "/v1/config",
        headers=headers,
        json={
            "operations": [
                {
                    "source_id": source_id,
                    "path": "llm.models.gpt_5_5.provider",
                    "op": "set",
                    "value": "openai_proxy",
                }
            ]
        },
    )
    assert switched.status_code == 200
    switched_generation = switched.json()["generation_id"]
    switched_source = model_path.read_text(encoding="utf-8")
    assert 'provider = "openai_proxy"' in switched_source
    assert "[llm.models.gpt_5_5.adapter_options]" in switched_source
    assert 'reasoning_keep = "encrypted"' in switched_source
    assert "[llm.models.gpt_5_5.request_overrides]" in switched_source
    assert "temperature = 0.4" in switched_source

    incompatible = client.patch(
        "/v1/config",
        headers=headers,
        json={
            "operations": [
                {
                    "source_id": source_id,
                    "path": "llm.models.gpt_5_5.provider",
                    "op": "set",
                    "value": "kimi",
                }
            ]
        },
    )

    assert incompatible.status_code == 422
    assert incompatible.json()["error"]["code"] == "config.invalid"
    assert model_path.read_text(encoding="utf-8") == switched_source
    runtime = endpoint.configuration.status()["runtime"]
    assert isinstance(runtime, dict)
    assert runtime["generation_id"] == switched_generation


def test_agent_workspace_mutation_reaches_endpoint_event_stream(
    tmp_path: Path,
) -> None:
    note = tmp_path / "runtime" / "workspace" / "note.md"
    note.parent.mkdir(parents=True)
    note.write_text("old text", encoding="utf-8")
    app = (
        TinySoulAppBuilder(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_app_settings(AppSettings(interactive=False))
        .with_loop_settings(LoopSettings(user=TurnSettings(max_cycles=2)))
        .with_endpoint(EndpointSettings(token="x" * 32))
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
                            name="workspace.patch",
                            arguments={
                                "target_link": "workspace:note.md",
                                "old_text": "old text",
                                "new_text": "new text",
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

    outcome = app.run_once("update the note")

    assert outcome.answered is True
    assert note.read_text(encoding="utf-8") == "new text"
    assert app.endpoint is not None
    page = app.endpoint.events.replay(
        after=0,
        mode=ObservationLevel.NORMAL,
        limit=200,
    )
    changes = [
        event
        for event in page.events
        if event.name == "workspace.changed"
        and event.payload["operation"] == "patch"
    ]
    assert len(changes) == 1
    assert changes[0].source == "workspace.engine"
    assert changes[0].payload["links"] == ["workspace:note.md"]


def test_app_builder_run_once_answers_with_real_action_and_context(
    tmp_path: Path,
) -> None:
    recorder = _CompletionRecorder()
    app = (
        TinySoulAppBuilder(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_app_settings(AppSettings(interactive=False))
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

    outcome = app.run_once("please answer")

    assert outcome.answered is True
    assert outcome.context_completion is not None
    assert len(outcome.context_completion.trace.entries) == 2
    assert outcome.context_completion.inputs[0].text == "please answer"
    assert len(recorder.completions) == 1
    assert recorder.completions[0].output is not None
    assert recorder.completions[0].output.text == "done"


def test_app_builder_runs_resource_conversion_through_real_action_chain(
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
        TinySoulAppBuilder(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_app_settings(AppSettings(interactive=False))
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

    outcome = app.run_once("convert the PDF")

    assert outcome.answered is True
    markdown = workspace_root / "converted" / "blank.md"
    page = workspace_root / "converted" / "blank.assets" / "page-001.png"
    assert markdown.is_file()
    assert "workspace:converted/blank.assets/page-001.png" in markdown.read_text(
        encoding="utf-8"
    )
    assert page.is_file()


def test_app_builder_cycle_limit_returns_exhausted_turn(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "doc.md").write_text("hello", encoding="utf-8")
    config = _test_config(
        tmp_path,
        {"workspace.root": str(workspace_root)},
    )
    app = (
        TinySoulAppBuilder(root=tmp_path)
        .with_config_environment(config)
        .with_app_settings(AppSettings(interactive=False))
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
                            name="workspace.scan",
                            arguments={},
                            kind=ToolKind.ACTION,
                        )
                    ),
                )
            )
        )
        .build()
    )

    outcome = app.run_once("scan only")

    assert outcome.answered is False
    assert outcome.exhausted is True
    assert outcome.context_completion is not None


def test_program_runner_idle_exit_ends_program(tmp_path: Path) -> None:
    app = (
        TinySoulAppBuilder(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_app_settings(AppSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
        .build()
    )

    app.submit_input("exit")
    outcome = app.run()

    assert outcome.turns == ()
    assert outcome.transfer is not None
    assert outcome.transfer.action is RuntimeTransferAction.END
    assert outcome.transfer.target.level is RunLevel.PROGRAM


def test_turn_runner_ignores_stop_control_without_turn_scope(tmp_path: Path) -> None:
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
        TinySoulAppBuilder(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_app_settings(AppSettings(interactive=False))
        .with_signal_bus(bus)
        .with_llm_runner(llm)
        .build()
    )
    bus.emit(
        build_control_request_signal(
            LoopControlKind.STOP_TURN,
            scope=app.program_runner.scope,
            source="test",
            text="stop",
        )
    )

    outcome = app.run_once("please stop")

    assert outcome.answered is True
    assert outcome.transfer is None
    assert outcome.context_completion is not None
    assert len(llm.calls) == 3


def test_app_builder_missing_agent_is_context_startup_failure(tmp_path: Path) -> None:
    config = _test_config(
        tmp_path,
        {"home.root": str(tmp_path / "missing_home")},
    )

    with pytest.raises(RuntimeException) as raised:
        (
            TinySoulAppBuilder(root=tmp_path)
            .with_config_environment(config)
            .with_app_settings(AppSettings(interactive=False))
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
            "infra",
            "infra.embedding.batch_size",
            "infra.configuration_failed",
        ),
        (
            {"workspace.max_files": 0},
            "workspace",
            "workspace.max_files",
            None,
        ),
        (
            {"capabilities.script.max_source_chars": 0},
            "script",
            "capabilities.script.max_source_chars",
            "script.configuration_failed",
        ),
        (
            {
                "capabilities.script.enabled": True,
                "capabilities.script.bash.enabled": True,
                "capabilities.script.bash.executable": (
                    "tinysoul-missing-bash-for-test"
                ),
            },
            "script",
            "capabilities.dependencies.script.bash",
            "script.configuration_failed",
        ),
        (
            {"capabilities.supervised_process.max_runtime_seconds": 0},
            "supervised_process",
            "capabilities.supervised_process.max_runtime_seconds",
            "supervised_process.configuration_failed",
        ),
        (
            {
                "capabilities.shell.enabled": True,
                "capabilities.shell.powershell.enabled": False,
                "capabilities.shell.cmd.enabled": True,
                "capabilities.shell.cmd.executable": "tinysoul-missing-cmd-for-test",
                "capabilities.shell.bash.enabled": False,
            },
            "shell",
            "capabilities.dependencies.shell.cmd",
            "shell.configuration_failed",
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
        "script-config",
        "script-dependency",
        "supervised-process-config",
        "shell-dependency",
        "loop-config",
        "loop-task-profile",
    ),
)
def test_app_builder_maps_owned_startup_failure(
    tmp_path: Path,
    overrides: dict[str, object],
    module: str,
    key: str,
    kind: str | None,
) -> None:
    config = _test_config(tmp_path, overrides)

    with pytest.raises(RuntimeException) as raised:
        (
            TinySoulAppBuilder(root=tmp_path)
            .with_config_environment(config)
            .with_app_settings(AppSettings(interactive=False))
            .with_llm_runner(FakeLLM(()))
            .build()
        )

    exc = raised.value
    assert exc.reason == RUNTIME_STARTUP_FAILED
    assert exc.payload["module"] == module
    assert exc.payload["key"] == key
    if kind is not None:
        assert exc.payload["kind"] == kind


def test_app_builder_corrupt_manifest_is_workspace_startup_failure(
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
            TinySoulAppBuilder(root=tmp_path)
            .with_config_environment(config)
            .with_app_settings(AppSettings(interactive=False))
            .with_llm_runner(FakeLLM(()))
            .build()
        )

    assert raised.value.reason == RUNTIME_STARTUP_FAILED
    assert raised.value.payload["module"] == "workspace"


def test_app_builder_does_not_map_programming_errors_to_startup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = (
        TinySoulAppBuilder(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_app_settings(AppSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
    )

    def explode(*args, **kwargs):
        raise RuntimeError("programming error")

    monkeypatch.setattr(builder, "_build_workspace", explode)

    with pytest.raises(RuntimeError, match="programming error"):
        builder.build()


def test_app_builder_app_config_error_is_app_startup_failure(tmp_path: Path) -> None:
    config = _test_config(tmp_path, {"app.interactive": "bad"})

    with pytest.raises(RuntimeException) as raised:
        (
            TinySoulAppBuilder(root=tmp_path)
            .with_config_environment(config)
            .with_loop_settings(LoopSettings())
            .with_llm_runner(FakeLLM(()))
            .build()
        )

    exc = raised.value
    assert exc.reason == RUNTIME_STARTUP_FAILED
    assert exc.payload["module"] == "app"
    assert exc.payload["key"] == "app.interactive"


def test_app_builder_llm_config_error_is_llm_startup_failure(tmp_path: Path) -> None:
    config = _test_config(tmp_path, {"llm.tasks.framework.models": ["missing_model"]})

    with pytest.raises(RuntimeException) as raised:
        (
            TinySoulAppBuilder(root=tmp_path)
            .with_config_environment(config)
            .with_app_settings(AppSettings(interactive=False))
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
    response = client.get("/v1/config/actions", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, dict)
    actions = payload.get("actions")
    assert isinstance(actions, list)
    for item in actions:
        if isinstance(item, dict) and item.get("id") == action_id:
            return to_json_object(item)
    raise AssertionError(f"Missing Action catalog entry: {action_id}")


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
        "app.interactive": False,
        "home.root": str(home_root),
        "home.runtime_root": str(tmp_path / "runtime" / "home"),
        "memory.root": str(tmp_path / "memory"),
        "session.root": str(tmp_path / "runtime" / "session"),
        "workspace.root": str(tmp_path / "runtime" / "workspace"),
        "maintenance.archive_root": str(tmp_path / "archive"),
        "maintenance.runtime_root": str(tmp_path / "runtime" / "maintenance"),
    }
    if overrides is not None:
        values.update(overrides)
    return ConfigEnvironment.from_project_root(root=project_root, overrides=values)
