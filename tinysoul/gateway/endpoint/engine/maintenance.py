"""Endpoint Reflection availability and request engine."""

from __future__ import annotations


from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.infra.time import CalendarDay, CalendarDayError
from tinysoul.plugins.reflection import (ReflectionContractError, ReflectionError, ReflectionScope)
from tinysoul.runtime import RuntimeGatewayError
from tinysoul.kernel.loop.errors import LoopError

from ..errors import EndpointRequestError
from .context import EndpointEngineContext


class EndpointReflectionEngine:
    """Translate Reflection requests through the shared App gateway."""

    def __init__(self, context: EndpointEngineContext) -> None:
        self._context = context

    async def status(self) -> JsonObject:
        try:
            availability = await self._context.services.reflection_status()
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
        instructions: str = "",
    ) -> JsonObject:
        if kind not in {"home", "memory"}:
            raise EndpointRequestError(
                status_code=422,
                code="maintenance.kind_invalid",
                message="Reflection kind must be home or memory.",
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
                instructions=instructions,
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
