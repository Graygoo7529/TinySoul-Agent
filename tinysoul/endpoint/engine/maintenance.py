"""Endpoint Maintenance availability and request engine."""

from __future__ import annotations

from typing import Generic

from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.infra.time import BusinessDay, BusinessDayError
from tinysoul.maintenance import MaintenanceContractError, MaintenanceError, MaintenanceScope
from tinysoul.runtime import RuntimeGatewayError
from tinysoul.loop.errors import LoopError

from ..errors import EndpointRequestError
from .contracts import EndpointGenerationT
from .context import EndpointEngineContext


class EndpointMaintenanceEngine(Generic[EndpointGenerationT]):
    """Translate Maintenance requests through the shared App gateway."""

    def __init__(self, context: EndpointEngineContext[EndpointGenerationT]) -> None:
        self._context = context

    def status(self) -> JsonObject:
        try:
            runtime_handle = self._context.runtime_handle
            if runtime_handle is None:
                availability = self._context.maintenance.availability().to_json()
            else:
                with runtime_handle.read() as generation:
                    availability = generation.maintenance.availability().to_json()
        except (LoopError, MaintenanceError) as exc:
            raise EndpointRequestError(
                status_code=409,
                code="program.not_ready",
                message="TinySoul active day is not ready.",
                details={"error_type": type(exc).__name__},
            ) from exc
        return {"availability": availability}

    def request(
        self,
        *,
        kind: str,
        target_day: str,
        metadata: JsonObject,
        command_id: str = "",
    ) -> JsonObject:
        if kind not in {"daily", "home", "memory"}:
            raise EndpointRequestError(
                status_code=422,
                code="maintenance.kind_invalid",
                message="Maintenance kind must be daily, home, or memory.",
            )
        if kind == "memory" and not target_day:
            raise EndpointRequestError(
                status_code=422,
                code="maintenance.target_day_required",
                message="Memory Maintenance requires target_day.",
            )
        day = None
        if target_day:
            if kind != "memory":
                raise EndpointRequestError(
                    status_code=422,
                    code="maintenance.target_day_invalid",
                    message="Only Memory Maintenance accepts target_day.",
                )
            try:
                day = BusinessDay.parse(target_day)
            except (BusinessDayError, MaintenanceContractError) as exc:
                raise EndpointRequestError(
                    status_code=422,
                    code="maintenance.target_day_invalid",
                    message="Maintenance target_day must use YYYY-MM-DD.",
                ) from exc
        try:
            receipt = self._context.gateway.request_maintenance(
                MaintenanceScope(kind),
                target_day=day,
                source="endpoint",
                metadata=to_json_object(metadata),
                command_id=command_id or None,
            )
        except RuntimeGatewayError as exc:
            raise EndpointRequestError(
                status_code=409,
                code="maintenance.rejected",
                message=str(exc),
            ) from exc
        return receipt.to_json()
