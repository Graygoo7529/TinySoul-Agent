"""Maintenance availability and request routes."""

from fastapi import FastAPI

from tinysoul.infra.json import JsonObject, to_json_object

from ...engine import EndpointEngine
from ..schemas import MaintenanceRequest


def register_maintenance_routes(app: FastAPI, engine: EndpointEngine) -> None:
    @app.get("/v1/maintenance")
    def maintenance_status() -> JsonObject:
        return engine.maintenance.status()

    @app.post("/v1/maintenance", status_code=202)
    def request_maintenance(body: MaintenanceRequest) -> JsonObject:
        return engine.maintenance.request(
            kind=body.kind,
            target_day=body.target_day,
            metadata=to_json_object(body.metadata),
            command_id=body.command_id,
        )
