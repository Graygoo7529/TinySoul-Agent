from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
import httpx
import pytest

from tinysoul.app import (
    CommandReceipt,
    ObservationRoute,
    ObservationRouter,
)
from tinysoul.endpoint import (
    EndpointContractError,
    EndpointEngine,
    EndpointEventBuffer,
    EndpointSettings,
)
from tinysoul.endpoint.server import EndpointASGIServer, create_endpoint_app
from tinysoul.infra.json import JsonObject
from tinysoul.infra.time import BusinessDay
from tinysoul.loop import LoopControlKind
from tinysoul.maintenance import (
    DailyLifecycleCoordinator,
    MaintenanceAvailability,
    MaintenanceScope,
)
from tinysoul.runtime import (
    ObservationEvent,
    ObservationLevel,
    RunLevel,
    RunScope,
)
from tinysoul.session import SessionEngine, SessionSettings
from tinysoul.workspace import WorkspaceEngineBuilder, WorkspaceManifest, WorkspaceSettings


DAY = BusinessDay.parse("2026-07-19")
TOKEN = "endpoint-test-token-0000000000000000"


@pytest.mark.parametrize("value", [0.0, -1.0, True])
def test_endpoint_settings_reject_invalid_websocket_heartbeat(
    value: float | bool,
) -> None:
    with pytest.raises(EndpointContractError, match="heartbeat"):
        EndpointSettings(token=TOKEN, websocket_heartbeat_seconds=value)


def test_endpoint_auth_input_and_status(tmp_path: Path) -> None:
    engine, gateway = _engine(tmp_path)
    client = TestClient(create_endpoint_app(engine, engine.settings))

    assert client.get("/v1/status").status_code == 401
    preflight = client.options(
        "/v1/status",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    assert preflight.status_code == 200
    status = client.get("/v1/status", headers=_auth()).json()
    assert status["ready"] is True
    assert status["active_day"] == str(DAY)
    openapi = client.get("/openapi.json", headers=_auth()).json()
    assert "/v1/events" in openapi["paths"]
    assert "/v1/workspace/blob" in openapi["paths"]
    assert "/v1/maintenance/decision" not in openapi["paths"]
    assert all(not path.startswith("/v1/session/") for path in openapi["paths"])

    response = client.post(
        "/v1/input",
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
        "/v1/control",
        headers=_auth(),
        json={"kind": "exit_program"},
    )
    assert response.status_code == 202
    assert gateway.controls[0][0] is LoopControlKind.EXIT_PROGRAM

    maintenance = client.get("/v1/maintenance", headers=_auth()).json()
    assert maintenance["availability"]["checked_day"] == str(DAY)
    assert maintenance["availability"]["home_pending"] is False
    response = client.post(
        "/v1/maintenance",
        headers=_auth(),
        json={"kind": "memory", "target_day": "2026-07-18", "command_id": "work_ui"},
    )
    assert response.status_code == 202
    assert response.json()["command_id"] == "work_ui"
    assert gateway.maintenance_requests == [
        (
            MaintenanceScope.MEMORY,
            BusinessDay.parse("2026-07-18"),
            False,
            "endpoint",
        )
    ]


def test_endpoint_hides_unexpected_exception_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, _gateway = _engine(tmp_path)

    def fail_status() -> JsonObject:
        raise OSError("B:\\private\\workspace")

    monkeypatch.setattr(engine, "status", fail_status)
    client = TestClient(
        create_endpoint_app(engine, engine.settings),
        raise_server_exceptions=False,
    )

    response = client.get("/v1/status", headers=_auth())

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "endpoint.internal",
            "message": "Endpoint request failed.",
            "details": {"error_type": "OSError"},
        }
    }
    assert "private" not in response.text


def test_endpoint_workspace_cas_trash_and_restore(tmp_path: Path) -> None:
    engine, gateway = _engine(tmp_path)
    client = TestClient(create_endpoint_app(engine, engine.settings))

    manifest = client.get("/v1/workspace/manifest", headers=_auth()).json()
    revision = manifest["revision"]
    created = client.put(
        "/v1/workspace/resource",
        headers=_auth(),
        json={
            "link": "workspace:notes/demo.md",
            "text": "first",
            "expected_revision": revision,
        },
    )
    assert created.status_code == 200
    body = created.json()
    digest = body["record"]["digest"]
    revision = body["manifest"]["revision"]
    assert gateway.synced[-1].revision == revision
    assert gateway.observed[-1].name == "workspace.changed"
    replayed = engine.replay_events(
        after=0,
        mode=ObservationLevel.NORMAL,
        limit=20,
    )
    assert replayed.events[-1].name == "workspace.changed"

    read = client.get(
        "/v1/workspace/resource",
        headers=_auth(),
        params={"link": "workspace:notes/demo.md"},
    ).json()
    assert read["text"] == "first"
    assert read["digest"] == digest

    stale = client.put(
        "/v1/workspace/resource",
        headers=_auth(),
        json={
            "link": "workspace:notes/demo.md",
            "text": "stale",
            "overwrite": True,
            "expected_digest": digest,
            "expected_revision": revision - 1,
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "workspace.conflict"

    trashed = client.post(
        "/v1/workspace/trash",
        headers=_auth(),
        json={
            "link": "workspace:notes/demo.md",
            "expected_digest": digest,
            "expected_revision": revision,
        },
    )
    assert trashed.status_code == 200
    trash = trashed.json()["trash"]
    revision = trashed.json()["manifest"]["revision"]
    assert trash["ref"].startswith("trash:workspace/")

    restored = client.post(
        "/v1/workspace/restore",
        headers=_auth(),
        json={"trash_ref": trash["ref"], "expected_revision": revision},
    )
    assert restored.status_code == 200
    assert restored.json()["record"]["link"] == "workspace:notes/demo.md"


def test_endpoint_workspace_blob_round_trip(tmp_path: Path) -> None:
    engine, _gateway = _engine(tmp_path)
    client = TestClient(create_endpoint_app(engine, engine.settings))
    revision = client.get(
        "/v1/workspace/manifest",
        headers=_auth(),
    ).json()["revision"]
    data = b"\x00\x01\x02tiny-soul"

    written = client.put(
        "/v1/workspace/blob",
        headers={**_auth(), "Content-Type": "application/octet-stream"},
        params={
            "link": "workspace:assets/data.bin",
            "expected_revision": revision,
        },
        content=data,
    )

    assert written.status_code == 200
    record = written.json()["record"]
    assert record["kind"] == "binary"
    response = client.get(
        "/v1/workspace/blob",
        headers=_auth(),
        params={"link": record["link"]},
    )
    assert response.status_code == 200
    assert response.content == data
    assert response.headers["x-tinysoul-digest"] == record["digest"]


def test_workspace_observation_failure_does_not_change_mutation_result(
    tmp_path: Path,
) -> None:
    engine, gateway = _engine(tmp_path, event_max_bytes=1)
    client = TestClient(create_endpoint_app(engine, engine.settings))
    revision = client.get(
        "/v1/workspace/manifest",
        headers=_auth(),
    ).json()["revision"]

    response = client.put(
        "/v1/workspace/resource",
        headers=_auth(),
        json={
            "link": "workspace:committed.md",
            "text": "committed",
            "expected_revision": revision,
        },
    )

    assert response.status_code == 200
    assert gateway.synced[-1].revision == response.json()["manifest"]["revision"]
    assert gateway.observed[-1].name == "workspace.changed"
    assert engine.events.latest_sequence == 0


def test_endpoint_event_replay_filter_and_websocket_auth(tmp_path: Path) -> None:
    engine, _gateway = _engine(tmp_path, websocket_heartbeat_seconds=0.05)
    after = engine.events.latest_sequence
    engine.events.write(
        ObservationEvent(
            name="turn.started",
            level=ObservationLevel.NORMAL,
            source="test",
        )
    )
    engine.events.write(
        ObservationEvent(
            name="llm.model.request",
            level=ObservationLevel.MODEL,
            source="test",
            payload={"messages": [{"role": "user", "content": "complete"}]},
        )
    )
    client = TestClient(create_endpoint_app(engine, engine.settings))

    normal = client.get(
        "/v1/events",
        headers=_auth(),
        params={"after": after, "mode": "normal"},
    ).json()
    assert [event["name"] for event in normal["events"]] == ["turn.started"]

    with client.websocket_connect("/v1/events/ws") as websocket:
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


def test_endpoint_asgi_server_uses_prebound_random_port(tmp_path: Path) -> None:
    engine, _gateway = _engine(tmp_path)
    server = EndpointASGIServer(engine=engine, settings=engine.settings)
    server.start()
    try:
        response = httpx.get(
            f"http://{engine.settings.host}:{server.port}/v1/health",
            timeout=5.0,
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True}
    finally:
        server.stop()


def _engine(
    tmp_path: Path,
    *,
    event_max_bytes: int = 1024 * 1024,
    websocket_heartbeat_seconds: float = 15.0,
) -> tuple[EndpointEngine, _EndpointGateway]:
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
    daily = DailyLifecycleCoordinator(
        archive_root=tmp_path / "archive",
        session=session,
        workspace=workspace,
    )
    daily.ensure_active_day(
        DAY,
        now=datetime(2026, 7, 19, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    settings = EndpointSettings(
        token=TOKEN,
        websocket_heartbeat_seconds=websocket_heartbeat_seconds,
    )
    engine = EndpointEngine(
        settings=settings,
        events=events,
        gateway=gateway,
        workspace=workspace,
        maintenance=_EndpointMaintenance(daily),
    )
    return engine, gateway


@dataclass
class _EndpointMaintenance:
    daily: DailyLifecycleCoordinator

    def active_day_lease(self):
        return self.daily.active_day_lease()

    def availability(self) -> MaintenanceAvailability:
        return MaintenanceAvailability(checked_day=DAY)


@dataclass
class _EndpointGateway:
    inputs: list[tuple[str, str, JsonObject]] = field(default_factory=list)
    controls: list[tuple[LoopControlKind, str, str, JsonObject]] = field(
        default_factory=list
    )
    synced: list[WorkspaceManifest] = field(default_factory=list)
    observed: list[ObservationEvent] = field(default_factory=list)
    maintenance_requests: list[
        tuple[MaintenanceScope, BusinessDay | None, bool, str]
    ] = field(
        default_factory=list
    )

    @property
    def active_turn_scope(self) -> RunScope | None:
        return None

    @property
    def current_scope(self) -> RunScope:
        return RunScope().push(RunLevel.PROGRAM, "program")

    def submit_user_input(
        self,
        text: str,
        *,
        source: str,
        metadata: JsonObject,
        command_id: str | None = None,
    ) -> CommandReceipt:
        self.inputs.append((text, source, metadata))
        return CommandReceipt(True, command_id or "command_test", "user_turn", "queued")

    def request_control(
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

    def request_maintenance(
        self,
        scope: MaintenanceScope | str,
        *,
        target_day,
        rebuild_memory: bool,
        source: str,
        metadata: JsonObject,
        command_id: str | None = None,
    ) -> CommandReceipt:
        typed_scope = (
            scope if isinstance(scope, MaintenanceScope) else MaintenanceScope(scope)
        )
        self.maintenance_requests.append(
            (typed_scope, target_day, rebuild_memory, source)
        )
        return CommandReceipt(
            True,
            command_id or "command_maintenance",
            "maintenance",
            "queued",
        )

    def sync_workspace_context(
        self,
        manifest: WorkspaceManifest,
        *,
        source: str,
    ) -> None:
        self.synced.append(manifest)

    def write(self, event: ObservationEvent) -> None:
        self.observed.append(event)


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}
