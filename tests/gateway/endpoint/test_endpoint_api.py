from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
import httpx
import pytest

from tinysoul.environment.inputs import CommandReceipt
from tinysoul.agent import TurnHandle, TurnSnapshot, UserTurnRequest, ReflectionRequest
from tinysoul.kernel.jobs import JobSnapshot
from tinysoul.kernel.loop.interaction.inbox import InboxReceipt
from tinysoul.agent.errors import (
    AgentSDKError,
    AgentServiceStaleError,
    AgentServiceUnavailableError,
)
from tinysoul.agent.observation.outputs import ObservationRoute
from tinysoul.agent.observation.outputs import ObservationRouter
from tinysoul.gateway.endpoint import (
    EndpointContractError,
    EndpointEngine,
    EndpointEventBuffer,
    EndpointSettings,
)
from tinysoul.gateway.endpoint.http import EndpointASGIServer, create_endpoint_app
from tinysoul.infra.config import ConfigController, ConfigEnvironment
from tinysoul.infra.json import JsonObject
from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.loop import LoopControlKind
from tinysoul.plugins.memory import MemoryEngine, MemorySettings
from tinysoul.plugins.archive import DailyLifecycleCoordinator
from tinysoul.plugins.reflection import ReflectionAvailability, ReflectionScope
from tinysoul.runtime import (
    ObservationEvent,
    ObservationLevel,
    RunLevel,
    RunScope,
    RuntimeException,
)
from tinysoul.plugins.session import SessionEngine, SessionSettings
from tinysoul.kernel.registration import Service, ServiceRegistry
from tinysoul.plugins.workspace.services import WorkspaceService
from tinysoul.plugins.workspace import (
    WorkspaceEngineBuilder,
    WorkspaceSettings,
)

DAY = CalendarDay.parse("2026-07-19")
TOKEN = "endpoint-test-token-0000000000000000"


@pytest.mark.parametrize("value", [0.0, -1.0, True])
def test_endpoint_settings_reject_invalid_websocket_heartbeat(
    value: float | bool,
) -> None:
    with pytest.raises(EndpointContractError, match="heartbeat"):
        EndpointSettings(token=TOKEN, websocket_heartbeat_seconds=value)


def test_endpoint_auth_input_and_status(tmp_path: Path) -> None:
    engine, gateway, _events = _engine(tmp_path)
    client = TestClient(create_endpoint_app(engine, engine.settings))

    assert client.get("/v2/status").status_code == 401
    assert client.post("/v2/restart").status_code == 401
    unavailable = client.post("/v2/restart", headers=_auth())
    assert unavailable.status_code == 409
    assert unavailable.json()["error"]["code"] == "endpoint.lifecycle_unavailable"
    preflight = client.options(
        "/v2/status",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    assert preflight.status_code == 200
    status = client.get("/v2/status", headers=_auth()).json()
    assert status["ready"] is True
    assert status["active_day"] == str(DAY)
    assert status["event_journal"]["enabled"] is False
    assert status["event_journal"]["degraded"] is False
    assert status["event_journal"] == {
        "enabled": False,
        "degraded": False,
        "oldest_sequence": None,
        "latest_sequence": 0,
    }
    openapi = client.get("/openapi.json", headers=_auth()).json()
    assert "/v2/events" in openapi["paths"]
    assert "/v2/config/actions" in openapi["paths"]
    assert "/v2/actions/catalog" not in openapi["paths"]
    assert "/v2/config/validate" not in openapi["paths"]
    assert "/v2/config/sections/{section_id}" not in openapi["paths"]
    assert "/v2/workspace/blob" in openapi["paths"]
    assert "put" in openapi["paths"]["/v2/workspace/blob"]
    assert "/v2/reflection/decision" not in openapi["paths"]
    assert all(not path.startswith("/v2/session/") for path in openapi["paths"])

    response = client.post(
        "/v2/input",
        headers=_auth(),
        json={
            "text": "hello",
            "metadata": {"client_id": "ui"},
            "command_id": "command_ui",
        },
    )
    assert response.status_code == 202
    assert response.json() == {
        "accepted": True,
        "command_id": "command_ui",
        "kind": "user_turn",
        "state": "queued",
    }
    assert gateway.inputs == [("hello", "endpoint", {"client_id": "ui"})]

    response = client.post(
        "/v2/control",
        headers=_auth(),
        json={"kind": "exit_program"},
    )
    assert response.status_code == 202
    assert gateway.controls[0][0] is LoopControlKind.EXIT_PROGRAM

    reflection = client.get("/v2/reflection", headers=_auth()).json()
    assert reflection["availability"]["checked_day"] == str(DAY)
    assert reflection["availability"]["home_pending"] is False
    response = client.post(
        "/v2/reflection",
        headers=_auth(),
        json={"kind": "memory", "target_day": "2026-07-18", "command_id": "work_ui"},
    )
    assert response.status_code == 202
    assert response.json()["command_id"] == "work_ui"
    assert gateway.reflection_requests == [
        (
            ReflectionScope.MEMORY,
            CalendarDay.parse("2026-07-18"),
            "endpoint",
        )
    ]

    missing_target = client.post(
        "/v2/reflection",
        headers=_auth(),
        json={"kind": "memory"},
    )
    assert missing_target.status_code == 422
    assert missing_target.json()["error"]["code"] == "turn.target_day_required"


def test_endpoint_hides_unexpected_exception_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, _gateway, _events = _engine(tmp_path)

    def fail_status() -> JsonObject:
        raise OSError("B:\\private\\workspace")

    monkeypatch.setattr(engine.runtime, "status", fail_status)
    client = TestClient(
        create_endpoint_app(engine, engine.settings),
        raise_server_exceptions=False,
    )

    response = client.get("/v2/status", headers=_auth())

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "endpoint.internal",
            "message": "Endpoint request failed.",
            "details": {"error_type": "OSError"},
        }
    }
    assert "private" not in response.text


@pytest.mark.parametrize(
    ("failure", "code"),
    (
        (AgentServiceStaleError("private details"), "service.stale"),
        (
            AgentServiceUnavailableError(
                module="workspace", kind="workspace.io_failed"
            ),
            "service.unavailable",
        ),
    ),
)
def test_endpoint_workspace_preserves_sdk_service_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: AgentSDKError,
    code: str,
) -> None:
    engine, _gateway, _events = _engine(tmp_path)
    client = TestClient(create_endpoint_app(engine, engine.settings))

    @asynccontextmanager
    async def unavailable(self: WorkspaceService) -> AsyncIterator[WorkspaceService]:
        raise failure
        yield self

    monkeypatch.setattr(WorkspaceService, "operation", unavailable)
    for response in (
        client.get("/v2/workspace/manifest", headers=_auth()),
        client.put(
            "/v2/workspace/resource",
            headers=_auth(),
            json={"link": "workspace:note.txt", "text": "content"},
        ),
    ):
        assert response.status_code == 409
        assert response.json()["error"]["code"] == code
        assert "private" not in response.text
    assert not (tmp_path / "workspace" / "note.txt").exists()


def test_endpoint_workspace_overwrite_trash_and_restore(tmp_path: Path) -> None:
    engine, gateway, _events = _engine(tmp_path)
    client = TestClient(create_endpoint_app(engine, engine.settings))

    manifest = client.get("/v2/workspace/manifest", headers=_auth()).json()
    created = client.put(
        "/v2/workspace/resource",
        headers=_auth(),
        json={
            "link": "workspace:notes/demo.md",
            "text": "first",
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert client.get("/v2/workspace/manifest", headers=_auth()).json() == body["manifest"]
    assert gateway.observed[-1].name == "workspace.changed"
    replayed = engine.events.replay(
        after=0,
        mode=ObservationLevel.NORMAL,
        limit=20,
    )
    assert replayed.events[-1].name == "workspace.changed"

    read = client.get(
        "/v2/workspace/resource",
        headers=_auth(),
        params={"link": "workspace:notes/demo.md"},
    ).json()
    assert read["text"] == "first"
    assert "digest" not in read

    stale = client.put(
        "/v2/workspace/resource",
        headers=_auth(),
        json={
            "link": "workspace:notes/demo.md",
            "text": "stale",
            "overwrite": False,
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "workspace.conflict"

    trashed = client.post(
        "/v2/workspace/trash",
        headers=_auth(),
        json={
            "link": "workspace:notes/demo.md",
        },
    )
    assert trashed.status_code == 200
    trash = trashed.json()["trash"]
    assert trash["ref"].startswith("trash:workspace/")

    restored = client.post(
        "/v2/workspace/restore",
        headers=_auth(),
        json={"trash_ref": trash["ref"]},
    )
    assert restored.status_code == 200
    assert restored.json()["record"]["link"] == "workspace:notes/demo.md"


def test_endpoint_workspace_directory_edit_move_tags_and_rejects_old_guards(
    tmp_path: Path,
) -> None:
    engine, gateway, _events = _engine(tmp_path)
    client = TestClient(create_endpoint_app(engine, engine.settings))
    assert (
        client.post(
            "/v2/workspace/directory", headers=_auth(), json={"link": "workspace:notes"}
        ).status_code
        == 200
    )
    created = client.put(
        "/v2/workspace/resource",
        headers=_auth(),
        json={"link": "workspace:notes/a.md", "text": "old"},
    )
    assert created.status_code == 200
    tagged = client.put(
        "/v2/workspace/tags",
        headers=_auth(),
        json={"link": "workspace:notes/a.md", "tags": ["pinned", "library"]},
    )
    assert tagged.status_code == 200
    edited = client.post(
        "/v2/workspace/edit",
        headers=_auth(),
        json={
            "link": "workspace:notes/a.md",
            "edits": [{"old_text": "old", "new_text": "new"}],
        },
    )
    assert edited.status_code == 200
    moved = client.post(
        "/v2/workspace/move",
        headers=_auth(),
        json={"link": "workspace:notes", "target_link": "workspace:renamed"},
    )
    assert moved.status_code == 200
    assert any(
        item["link"] == "workspace:renamed/a.md" for item in moved.json()["manifest"]["resources"]
    )
    assert (
        client.get(
            "/v2/workspace/resource",
            headers=_auth(),
            params={"link": "workspace:renamed/a.md"},
        ).json()["text"]
        == "new"
    )
    assert (
        client.put(
            "/v2/workspace/resource",
            headers=_auth(),
            json={
                "link": "workspace:renamed/a.md",
                "text": "unsafe",
                "overwrite": True,
                "expected_digest": "old",
            },
        ).status_code
        == 422
    )


def test_endpoint_workspace_blob_round_trip(tmp_path: Path) -> None:
    engine, _gateway, _events = _engine(tmp_path)
    client = TestClient(create_endpoint_app(engine, engine.settings))
    data = b"\x00\x01\x02tiny-soul"

    written = client.put(
        "/v2/workspace/blob",
        headers={**_auth(), "Content-Type": "application/octet-stream"},
        params={
            "link": "workspace:assets/data.bin",
        },
        content=data,
    )

    assert written.status_code == 200
    record = written.json()["record"]
    assert record["kind"] == "binary"
    response = client.get(
        "/v2/workspace/blob",
        headers=_auth(),
        params={"link": record["link"]},
    )
    assert response.status_code == 200
    assert response.content == data
    assert response.headers["x-tinysoul-size"] == str(len(data))


def test_workspace_observation_failure_does_not_change_mutation_result(
    tmp_path: Path,
) -> None:
    engine, gateway, events = _engine(tmp_path, event_max_bytes=1)
    client = TestClient(create_endpoint_app(engine, engine.settings))

    response = client.put(
        "/v2/workspace/resource",
        headers=_auth(),
        json={
            "link": "workspace:committed.md",
            "text": "committed",
        },
    )

    assert response.status_code == 200
    assert client.get("/v2/workspace/manifest", headers=_auth()).json() == response.json()["manifest"]
    assert gateway.observed[-1].name == "workspace.changed"
    assert events.latest_sequence == 0


def test_endpoint_event_replay_filter_and_websocket_auth(tmp_path: Path) -> None:
    engine, _gateway, events = _engine(tmp_path, websocket_heartbeat_seconds=0.05)
    after = events.latest_sequence
    events.write(
        ObservationEvent(
            name="turn.started",
            level=ObservationLevel.NORMAL,
            source="test",
        )
    )
    events.write(
        ObservationEvent(
            name="llm.model.request",
            level=ObservationLevel.MODEL,
            source="test",
            payload={"messages": [{"role": "user", "content": "complete"}]},
        )
    )
    client = TestClient(create_endpoint_app(engine, engine.settings))

    normal = client.get(
        "/v2/events",
        headers=_auth(),
        params={"after": after, "mode": "normal"},
    ).json()
    assert [event["name"] for event in normal["events"]] == ["turn.started"]

    with client.websocket_connect("/v2/events/ws") as websocket:
        websocket.send_json({"token": TOKEN, "after": after, "mode": "model"})
        authenticated = websocket.receive_json()
        assert authenticated["type"] == "authenticated"
        assert authenticated["instance_id"] == engine.settings.instance_id
        page = websocket.receive_json()
        assert page["type"] == "events"
        assert [event["name"] for event in page["events"]] == [
            "turn.started",
            "llm.model.request",
        ]


@pytest.mark.parametrize("cursor", ({"instance_id": "previous", "after": 100}, {"after": 100}))
def test_v2_replay_resets_old_instance_or_future_cursor(tmp_path: Path, cursor: dict[str, str | int]) -> None:
    engine, _, events = _engine(tmp_path, websocket_heartbeat_seconds=0.05)
    events.write(ObservationEvent(name="turn.started", source="test", level=ObservationLevel.NORMAL))
    client = TestClient(create_endpoint_app(engine, engine.settings))
    page = client.get("/v2/events", headers=_auth(), params=cursor).json()
    assert page["gap"] and page["instance_id"] == engine.settings.instance_id
    assert page["events"][-1]["name"] == "turn.started"
    with client.websocket_connect("/v2/events/ws") as websocket:
        websocket.send_json({"token": TOKEN, **cursor})
        assert websocket.receive_json()["protocol_version"] == 2
        replay = websocket.receive_json()
        assert replay["gap"] and replay["events"] == page["events"]
        heartbeat = websocket.receive_json()
        assert heartbeat["type"] == "heartbeat"
        assert heartbeat["next_sequence"] == page["next_sequence"]


async def test_endpoint_asgi_server_uses_prebound_random_port(tmp_path: Path) -> None:
    engine, _gateway, _events = _engine(tmp_path)
    server = EndpointASGIServer(engine=engine, settings=engine.settings)
    await server.start()
    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            response = await client.get(
                f"http://{engine.settings.host}:{server.port}/v2/health",
                timeout=5.0,
            )
        assert response.status_code == 200
        assert response.json() == {"ok": True}
    finally:
        await server.stop()


def test_config_routes_read_and_patch_project_source(tmp_path: Path) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (tmp_path / "tinysoul.toml").write_text(
        '[config]\ninclude = ["configs/action.toml"]\n',
        encoding="utf-8",
    )
    target = config_dir / "action.toml"
    target.write_text(
        "[action.llm_action]\ntimeout_seconds = 10.0\n",
        encoding="utf-8",
    )
    controller = ConfigController(
        root=tmp_path,
        environment=ConfigEnvironment.from_project_root(tmp_path, env={}),
    )
    engine, _gateway, _events = _engine(tmp_path, config=controller)
    client = TestClient(create_endpoint_app(engine, engine.settings))
    body = {
        "operations": [
            {
                "source_id": "project:configs/action.toml",
                "path": "action.llm_action.timeout_seconds",
                "op": "set",
                "value": 30.0,
            }
        ]
    }

    status = client.get("/v2/config", headers=_auth())
    assert status.status_code == 200
    assert (
        status.json()["fields"]["action.llm_action.timeout_seconds"]["writable"] is True
    )

    catalog = client.get("/v2/config/catalog", headers=_auth())
    assert catalog.status_code == 200
    assert any(
        field["path"] == "action.llm_action.timeout_seconds"
        for field in catalog.json()["fields"]
    )

    invalid_requests = (
        {
            "operations": [
                {
                    "source_id": "project:configs/action.toml",
                    "path": "action.llm_action.timeout_seconds",
                    "op": "set",
                }
            ]
        },
        {
            "operations": [
                {
                    "source_id": "project:configs/action.toml",
                    "path": "action.llm_action.timeout_seconds",
                    "op": "set",
                    "value": None,
                }
            ]
        },
        {
            "operations": [
                {
                    "source_id": "project:configs/action.toml",
                    "path": "action.llm_action.timeout_seconds",
                    "op": "delete",
                    "value": 1,
                }
            ]
        },
        {
            "operations": [
                {
                    "source_id": "project:configs/action.toml",
                    "path": "action.llm_action.timeout_seconds",
                    "op": "other",
                }
            ]
        },
    )
    for invalid in invalid_requests:
        response = client.patch("/v2/config", headers=_auth(), json=invalid)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "request.invalid"

    assert client.get("/v2/config/validate", headers=_auth()).status_code == 404
    assert (
        client.get(
            "/v2/config/sections/action",
            headers=_auth(),
        ).status_code
        == 404
    )

    patched = client.patch("/v2/config", headers=_auth(), json=body)
    assert patched.status_code == 200
    assert patched.json()["state"] == "saved"
    assert "timeout_seconds = 30.0" in target.read_text(encoding="utf-8")


def test_config_activation_failure_uses_config_error_and_keeps_file(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (tmp_path / "tinysoul.toml").write_text(
        '[config]\ninclude = ["configs/action.toml"]\n',
        encoding="utf-8",
    )
    target = config_dir / "action.toml"
    original = "[action.llm_action]\ntimeout_seconds = 10.0\n"
    target.write_text(original, encoding="utf-8")

    def fail_activation(_candidate: ConfigEnvironment):
        raise RuntimeException(
            reason="runtime.startup_failed",
            message="candidate failed",
        )

    controller = ConfigController(
        root=tmp_path,
        environment=ConfigEnvironment.from_project_root(tmp_path, env={}),
        activator=fail_activation,
    )
    engine, _gateway, _events = _engine(tmp_path, config=controller)
    client = TestClient(create_endpoint_app(engine, engine.settings))

    response = client.patch(
        "/v2/config",
        headers=_auth(),
        json={
            "operations": [
                {
                    "source_id": "project:configs/action.toml",
                    "path": "action.llm_action.timeout_seconds",
                    "op": "set",
                    "value": 30.0,
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["state"] == "saved"
    assert target.read_text(encoding="utf-8") != original
    reload_response = client.post("/v2/config/reload", headers=_auth())
    assert reload_response.status_code == 500
    assert reload_response.json()["error"]["code"] == "config.activation_failed"


def _engine(
    tmp_path: Path,
    *,
    event_max_bytes: int = 1024 * 1024,
    websocket_heartbeat_seconds: float = 15.0,
    config: ConfigController | None = None,
) -> tuple[EndpointEngine, _EndpointGateway, EndpointEventBuffer]:
    session = SessionEngine(SessionSettings(root=tmp_path / "session"))
    events = EndpointEventBuffer(capacity=32, max_bytes=event_max_bytes)
    gateway = _EndpointGateway()
    observations = ObservationRouter(
        mode=ObservationLevel.MODEL,
        routes=(
            ObservationRoute(sink=events, mode=ObservationLevel.MODEL),
            ObservationRoute(sink=gateway, mode=ObservationLevel.MODEL),
        ),
    )
    workspace = WorkspaceEngineBuilder(
        WorkspaceSettings(root=tmp_path / "workspace"),
        observations=observations,
    ).build()
    memory = MemoryEngine(
        settings=MemorySettings(root=tmp_path / "memory"),
        active_session_root=session.root,
    )
    daily = DailyLifecycleCoordinator(
        archive_root=tmp_path / "archive",
        session=session,
        workspace=workspace,
        memory=memory,
    )
    daily.ensure_active_day(
        DAY,
        now=datetime(2026, 7, 19, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    if config is None and not (tmp_path / "tinysoul.toml").exists():
        (tmp_path / "tinysoul.toml").write_text("", encoding="utf-8")
    settings = EndpointSettings(
        token=TOKEN,
        websocket_heartbeat_seconds=websocket_heartbeat_seconds,
    )
    engine = EndpointEngine(
        settings=settings,
        events=events,
        gateway=gateway,
        services=_EndpointServices(WorkspaceService(workspace)),
        config=config
        or ConfigController(
            root=tmp_path,
            environment=ConfigEnvironment.from_project_root(tmp_path, env={}),
        ),
    )
    return engine, gateway, events


class _EndpointServices:
    def __init__(self, workspace: WorkspaceService) -> None:
        self.registry = ServiceRegistry((Service(WorkspaceService, workspace),))

    def turn_snapshot(self, turn_id: str) -> TurnSnapshot | None:
        return None

    def turn_jobs(self, turn_id: str) -> tuple[JobSnapshot, ...] | None:
        return None

    async def stop_job(self, turn_id: str, job_id: str) -> JobSnapshot:
        raise AgentSDKError("Test service has no Jobs")

    def runtime_status(self, *, credentials: bool = False) -> JsonObject:
        return {
            "generation_id": "test",
            "activity": "idle",
            "activation": "active",
            "active_day": str(DAY),
        }

    async def action_catalog(self, *, scenario: str = "user") -> JsonObject:
        return {"domains": [], "actions": []}

    async def reflection_status(
        self, *, before: CalendarDay | None = None
    ) -> JsonObject:
        return ReflectionAvailability(checked_day=DAY).to_json()


@dataclass
class _EndpointGateway:
    @property
    def commands(self) -> _EndpointGateway:
        return self

    async def submit_turn(self, request: UserTurnRequest | ReflectionRequest) -> TurnHandle:
        if isinstance(request, ReflectionRequest):
            self.reflection_requests.append((request.scope, request.target_day, request.source))
        else:
            self.inputs.append((request.text, request.source, request.metadata))
        return TurnHandle(request)

    async def append_input(self, turn_id: str, text: str, *, input_id: str = "") -> InboxReceipt:
        raise AgentSDKError("No active Turn")

    async def reply(self, turn_id: str, question_id: str, response: str) -> InboxReceipt:
        raise AgentSDKError("No active Turn")

    async def grant_cycles(self, turn_id: str, request_id: str, count: int) -> bool:
        raise AgentSDKError("No active Turn")

    async def cancel_turn(self, turn_id: str) -> bool:
        return False

    inputs: list[tuple[str, str, JsonObject]] = field(default_factory=list)
    controls: list[tuple[LoopControlKind, str, str, JsonObject]] = field(
        default_factory=list
    )
    observed: list[ObservationEvent] = field(default_factory=list)
    reflection_requests: list[tuple[ReflectionScope, CalendarDay | None, str]] = field(
        default_factory=list
    )

    @property
    def active_turn_scope(self) -> RunScope | None:
        return None

    @property
    def current_scope(self) -> RunScope:
        return RunScope().push(RunLevel.AGENT, "program")

    async def submit_user_input(
        self,
        text: str,
        *,
        source: str,
        metadata: JsonObject,
        command_id: str | None = None,
    ) -> CommandReceipt:
        self.inputs.append((text, source, metadata))
        return CommandReceipt(True, command_id or "command_test", "user_turn", "queued")

    async def request_control(
        self,
        kind: LoopControlKind,
        *,
        source: str,
        text: str,
        metadata: JsonObject,
    ) -> CommandReceipt:
        self.controls.append((kind, source, text, metadata))
        return CommandReceipt(
            True,
            str(metadata.get("command_id", "command_test")),
            kind.value,
            "queued",
        )

    async def request_reflection(
        self,
        scope: ReflectionScope | str,
        *,
        target_day,
        source: str,
        metadata: JsonObject,
        command_id: str | None = None,
        instructions: str = "",
    ) -> CommandReceipt:
        typed_scope = (
            scope if isinstance(scope, ReflectionScope) else ReflectionScope(scope)
        )
        self.reflection_requests.append((typed_scope, target_day, source))
        return CommandReceipt(
            True,
            command_id or "command_reflection",
            "reflection",
            "queued",
        )

    def write(self, event: ObservationEvent) -> None:
        self.observed.append(event)


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}
