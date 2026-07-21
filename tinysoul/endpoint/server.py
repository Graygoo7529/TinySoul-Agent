"""FastAPI/Uvicorn adapter for the local Endpoint Engine."""

from __future__ import annotations

import asyncio
from hmac import compare_digest
import socket
from threading import Thread
from time import monotonic, sleep
from typing import Literal

from fastapi import Body, FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response
import uvicorn

from tinysoul.home import HomeMaintenanceDecision
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.runtime import ObservationLevel
from tinysoul.workspace import WorkspaceRetention

from .config import EndpointSettings
from .engine import EndpointControlKind, EndpointEngine
from .errors import EndpointRequestError, EndpointServerError


class InputRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    metadata: dict[str, object] = Field(default_factory=dict)
    command_id: str = Field(default="", max_length=128)


class ControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["stop_turn", "exit_program"]
    metadata: dict[str, object] = Field(default_factory=dict)
    command_id: str = Field(default="", max_length=128)


class MaintenanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["home", "memory"]
    target_day: str = ""
    metadata: dict[str, object] = Field(default_factory=dict)
    command_id: str = Field(default="", max_length=128)


class WorkspaceWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    link: str = Field(min_length=1)
    text: str
    overwrite: bool = False
    expected_digest: str = ""
    expected_revision: int = Field(ge=0)
    retention: Literal["ephemeral", "turn", "day", "persistent"] | None = None


class WorkspaceTrashRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    link: str = Field(min_length=1)
    expected_digest: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)


class WorkspaceRestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trash_ref: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)


class MaintenanceDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(min_length=1)
    decision: Literal["apply", "discard", "stop"]
    command_id: str = Field(default="", max_length=128)


def create_endpoint_app(
    engine: EndpointEngine,
    settings: EndpointSettings,
) -> FastAPI:
    app = FastAPI(
        title="TinySoul Local Endpoint",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "PUT", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=[
            "X-TinySoul-Link",
            "X-TinySoul-Digest",
            "X-TinySoul-Size",
        ],
    )

    @app.middleware("http")
    async def authenticate(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if request.method == "OPTIONS" or request.url.path == "/v1/health":
            return await call_next(request)
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                length = int(content_length)
            except ValueError:
                return _error_response(400, "request.invalid_length", "Invalid Content-Length.")
            if length > settings.max_request_bytes:
                return _error_response(413, "request.too_large", "Request body is too large.")
        authorization = request.headers.get("authorization", "")
        expected = f"Bearer {settings.token}"
        if not compare_digest(authorization, expected):
            return _error_response(401, "auth.unauthorized", "Bearer token is required.")
        return await call_next(request)

    @app.exception_handler(EndpointRequestError)
    async def endpoint_request_error(
        request: Request,
        error: EndpointRequestError,
    ) -> JSONResponse:
        return JSONResponse(status_code=error.status_code, content=error.to_json())

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(
            422,
            "request.invalid",
            "Request does not match the Endpoint contract.",
        )

    @app.exception_handler(Exception)
    async def unexpected_error(
        request: Request,
        error: Exception,
    ) -> JSONResponse:
        return _error_response(
            500,
            "endpoint.internal",
            "Endpoint request failed.",
            {"error_type": type(error).__name__},
        )

    @app.get("/v1/health")
    async def health() -> JsonObject:
        return {"ok": True}

    @app.get("/v1/status")
    async def status() -> JsonObject:
        return engine.status()

    @app.post("/v1/input", status_code=202)
    async def submit_input(body: InputRequest) -> JsonObject:
        return engine.submit_user_input(
            body.text,
            to_json_object(body.metadata),
            command_id=body.command_id,
        )

    @app.post("/v1/control", status_code=202)
    async def submit_control(body: ControlRequest) -> JsonObject:
        return engine.submit_control(
            EndpointControlKind(body.kind),
            to_json_object(body.metadata),
            command_id=body.command_id,
        )

    @app.get("/v1/maintenance")
    async def maintenance_status() -> JsonObject:
        return engine.maintenance_status()

    @app.post("/v1/maintenance", status_code=202)
    async def request_maintenance(body: MaintenanceRequest) -> JsonObject:
        return engine.request_maintenance(
            kind=body.kind,
            target_day=body.target_day,
            metadata=to_json_object(body.metadata),
            command_id=body.command_id,
        )

    @app.get("/v1/events")
    async def events(
        after: int = Query(default=0, ge=0),
        mode: ObservationLevel = Query(default=ObservationLevel.NORMAL),
        limit: int = Query(default=200, ge=1, le=1000),
    ) -> JsonObject:
        return engine.replay_events(after=after, mode=mode, limit=limit).to_json()

    @app.get("/v1/session/history")
    async def session_history() -> JsonObject:
        return engine.session_history()

    @app.get("/v1/session/recall")
    async def session_recall(
        ref: str = Query(min_length=1),
        max_chars: int | None = Query(default=None, ge=1),
        cursor: int = Query(default=0, ge=0),
    ) -> JsonObject:
        return engine.session_recall(ref, max_chars=max_chars, cursor=cursor)

    @app.get("/v1/workspace/manifest")
    async def workspace_manifest() -> JsonObject:
        return engine.workspace_manifest()

    @app.get("/v1/workspace/resource")
    async def workspace_resource(link: str = Query(min_length=1)) -> JsonObject:
        return engine.read_workspace_text(link)

    @app.get("/v1/workspace/blob")
    async def workspace_blob(link: str = Query(min_length=1)) -> Response:
        blob = engine.read_workspace_blob(link)
        return Response(
            content=blob.data,
            media_type=blob.media_type,
            headers={
                "X-TinySoul-Link": blob.link,
                "X-TinySoul-Digest": blob.digest,
                "X-TinySoul-Size": str(blob.size),
            },
        )

    @app.put("/v1/workspace/resource")
    async def write_workspace_resource(body: WorkspaceWriteRequest) -> JsonObject:
        retention = (
            WorkspaceRetention(body.retention) if body.retention is not None else None
        )
        return engine.write_workspace_text(
            link=body.link,
            text=body.text,
            overwrite=body.overwrite,
            expected_digest=body.expected_digest,
            expected_revision=body.expected_revision,
            retention=retention,
        )

    @app.put("/v1/workspace/blob")
    async def write_workspace_blob(
        body: bytes = Body(media_type="application/octet-stream"),
        link: str = Query(min_length=1),
        overwrite: bool = Query(default=False),
        expected_digest: str = Query(default=""),
        expected_revision: int = Query(ge=0),
        retention: WorkspaceRetention | None = Query(default=None),
    ) -> JsonObject:
        return engine.write_workspace_blob(
            link=link,
            data=body,
            overwrite=overwrite,
            expected_digest=expected_digest,
            expected_revision=expected_revision,
            retention=retention,
        )

    @app.get("/v1/workspace/trash")
    async def workspace_trash() -> JsonObject:
        return engine.workspace_trash()

    @app.post("/v1/workspace/trash")
    async def trash_workspace_resource(body: WorkspaceTrashRequest) -> JsonObject:
        return engine.trash_workspace_resource(
            link=body.link,
            expected_digest=body.expected_digest,
            expected_revision=body.expected_revision,
        )

    @app.post("/v1/workspace/restore")
    async def restore_workspace_resource(body: WorkspaceRestoreRequest) -> JsonObject:
        return engine.restore_workspace_resource(
            trash_ref=body.trash_ref,
            expected_revision=body.expected_revision,
        )

    @app.get("/v1/maintenance/decision")
    async def maintenance_decision() -> JsonObject:
        return engine.maintenance_decision()

    @app.post("/v1/maintenance/decision")
    async def resolve_maintenance_decision(
        body: MaintenanceDecisionRequest,
    ) -> JsonObject:
        decision = (
            None
            if body.decision == "stop"
            else HomeMaintenanceDecision(body.decision)
        )
        return engine.resolve_maintenance_decision(
            decision_id=body.decision_id,
            decision=decision,
            command_id=body.command_id,
        )

    @app.websocket("/v1/events/ws")
    async def events_websocket(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            auth = await asyncio.wait_for(websocket.receive_json(), timeout=5.0)
            if not isinstance(auth, dict):
                await websocket.close(code=1008)
                return
            token = auth.get("token")
            if not isinstance(token, str) or not compare_digest(token, settings.token):
                await websocket.close(code=1008)
                return
            after = _ws_non_negative_int(auth.get("after", 0), "after")
            mode = _ws_mode(auth.get("mode", ObservationLevel.NORMAL.value))
            await websocket.send_json(
                {
                    "type": "authenticated",
                    "protocol_version": 1,
                    "instance_id": settings.instance_id,
                    "project_identity": settings.project_identity,
                    "next_sequence": engine.events.latest_sequence,
                }
            )
            while True:
                page = await asyncio.to_thread(
                    engine.events.wait_after,
                    after=after,
                    mode=mode,
                    timeout_seconds=15.0,
                )
                if page.events or page.gap:
                    await websocket.send_json(
                        {"type": "events", **page.to_json()}
                    )
                else:
                    await websocket.send_json(
                        {"type": "heartbeat", "next_sequence": page.next_sequence}
                    )
                after = page.next_sequence
        except (WebSocketDisconnect, asyncio.TimeoutError):
            return
        except EndpointRequestError:
            await websocket.close(code=1008)

    return app


class EndpointASGIServer:
    """Run Uvicorn on a pre-bound loopback socket for race-free port 0."""

    def __init__(self, *, engine: EndpointEngine, settings: EndpointSettings) -> None:
        self._settings = settings
        self._app = create_endpoint_app(engine, settings)
        self._socket: socket.socket | None = None
        self._server: uvicorn.Server | None = None
        self._thread: Thread | None = None
        self._failure: BaseException | None = None
        self._port = 0

    @property
    def port(self) -> int:
        if self._port <= 0:
            raise EndpointServerError("Endpoint server has no bound port")
        return self._port

    def start(self) -> None:
        if self._thread is not None:
            raise EndpointServerError("Endpoint ASGI server is already started")
        family = socket.AF_INET6 if ":" in self._settings.host else socket.AF_INET
        bound = socket.socket(family, socket.SOCK_STREAM)
        try:
            bound.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            bound.bind((self._settings.host, self._settings.port))
            bound.listen(2048)
            self._port = int(bound.getsockname()[1])
            config = uvicorn.Config(
                self._app,
                host=self._settings.host,
                port=self._port,
                log_level="warning",
                access_log=False,
            )
            server = uvicorn.Server(config)
            thread = Thread(
                target=self._run,
                args=(server, bound),
                name="tinysoul-endpoint",
                daemon=True,
            )
            self._socket = bound
            self._server = server
            self._thread = thread
            thread.start()
            deadline = monotonic() + 10.0
            while not server.started and thread.is_alive() and monotonic() < deadline:
                sleep(0.01)
            if not server.started:
                failure = self._failure
                self.stop()
                detail = type(failure).__name__ if failure is not None else "timeout"
                raise EndpointServerError(
                    f"Endpoint ASGI server failed to start: {detail}"
                )
        except OSError as exc:
            bound.close()
            raise EndpointServerError(f"Endpoint bind failed: {exc}") from exc

    def stop(self) -> None:
        server = self._server
        thread = self._thread
        bound = self._socket
        self._server = None
        self._thread = None
        self._socket = None
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(timeout=10.0)
        if bound is not None:
            bound.close()
        if thread is not None and thread.is_alive():
            raise EndpointServerError("Endpoint ASGI server did not stop")

    def _run(self, server: uvicorn.Server, bound: socket.socket) -> None:
        try:
            server.run(sockets=[bound])
        except BaseException as exc:
            self._failure = exc


def _error_response(
    status_code: int,
    code: str,
    message: str,
    details: JsonObject | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
            }
        },
    )


def _ws_non_negative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EndpointRequestError(
            status_code=422,
            code="websocket.invalid_auth",
            message=f"WebSocket {name} must be a non-negative integer.",
        )
    return value


def _ws_mode(value: object) -> ObservationLevel:
    if not isinstance(value, str):
        raise EndpointRequestError(
            status_code=422,
            code="websocket.invalid_auth",
            message="WebSocket mode is invalid.",
        )
    try:
        return ObservationLevel(value)
    except ValueError as exc:
        raise EndpointRequestError(
            status_code=422,
            code="websocket.invalid_auth",
            message="WebSocket mode is invalid.",
        ) from exc
