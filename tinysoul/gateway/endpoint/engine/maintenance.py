"""Endpoint Reflection availability and request engine."""

from __future__ import annotations

from typing import Generic

from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.infra.time import CalendarDay, CalendarDayError
from tinysoul.plugins.reflection import (ReflectionContractError, ReflectionError, ReflectionScope)
from tinysoul.runtime import RuntimeGatewayError
from tinysoul.kernel.loop.errors import LoopError

from ..errors import EndpointRequestError
from .contracts import EndpointGenerationT
from .context import EndpointEngineContext


class EndpointReflectionEngine(Generic[EndpointGenerationT]):
    """Translate Reflection requests through the shared App gateway."""

    def __init__(self, context: EndpointEngineContext[EndpointGenerationT]) -> None:
        self._context = context

    def status(self) -> JsonObject:
        try:
            with self._context.services_lease() as services:
                maintenance = self._context.maintenance if services is None else services.maintenance
                availability = maintenance.availability().to_json()
        except (LoopError, ReflectionError) as exc:
            raise EndpointRequestError(
                status_code=409,
                code="program.not_ready",
                message="TinySoul active day is not ready.",
                details={"error_type": type(exc).__name__},
            ) from exc
        return {"availability": availability}

    async def request(
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
                message="Reflection kind must be daily, home, or memory.",
            )
        if kind == "memory" and not target_day:
            raise EndpointRequestError(
                status_code=422,
                code="maintenance.target_day_required",
                message="Memory Reflection requires target_day.",
            )
        day = None
        if target_day:
            if kind != "memory":
                raise EndpointRequestError(
                    status_code=422,
                    code="maintenance.target_day_invalid",
                    message="Only Memory Reflection accepts target_day.",
                )
            try:
                day = CalendarDay.parse(target_day)
            except (CalendarDayError, ReflectionContractError) as exc:
                raise EndpointRequestError(
                    status_code=422,
                    code="maintenance.target_day_invalid",
                    message="Reflection target_day must use YYYY-MM-DD.",
                ) from exc
        try:
            receipt = await self._context.gateway.request_maintenance(
                ReflectionScope(kind),
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
