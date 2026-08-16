"""Runtime status and command routes."""

from fastapi import FastAPI

from tinysoul.infra.json import JsonObject, to_json_object

from ...engine import EndpointControlKind, EndpointEngine
from ..schemas import ControlRequest, InputRequest


def register_runtime_routes(app: FastAPI, engine: EndpointEngine) -> None:
    @app.get("/v1/status")
    def status() -> JsonObject:
        return engine.runtime.status()

    @app.post("/v1/input", status_code=202)
    def submit_input(body: InputRequest) -> JsonObject:
        return engine.runtime.submit_user_input(
            body.text,
            to_json_object(body.metadata),
            command_id=body.command_id,
        )

    @app.post("/v1/control", status_code=202)
    def submit_control(body: ControlRequest) -> JsonObject:
        return engine.runtime.submit_control(
            EndpointControlKind(body.kind),
            to_json_object(body.metadata),
            command_id=body.command_id,
        )
