"""Endpoint Reflection availability and request engine."""

from __future__ import annotations


from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.infra.time import CalendarDay, CalendarDayError
from tinysoul.plugins.reflection import (
    ReflectionError,
)
from tinysoul.kernel.loop.errors import LoopError

from ..errors import EndpointRequestError
from .context import EndpointEngineContext
from .runtime import EndpointRuntimeEngine


class EndpointReflectionEngine:
    """Translate Reflection requests through the shared Agent gateway."""

    def __init__(self, context: EndpointEngineContext) -> None:
        self._context = context

    async def status(self, *, before: str | None = None) -> JsonObject:
        try:
            day = CalendarDay.parse(before) if before is not None else None
        except CalendarDayError as exc:
            raise EndpointRequestError(
                status_code=422,
                code="reflection.before_invalid",
                message="Reflection continuation must use YYYY-MM-DD.",
            ) from exc
        try:
            availability = await self._context.services.reflection_status(before=day)
        except (LoopError, ReflectionError) as exc:
            raise EndpointRequestError(
                status_code=409,
                code="agent.not_ready",
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
        return await EndpointRuntimeEngine(self._context).create_turn(
            kind=kind, text="", target_day=target_day, instructions=instructions,
            metadata=to_json_object(metadata), command_id=command_id,
        )
