"""Presentation protocol mapping over the project-scoped owner."""

from collections.abc import Awaitable

from tinysoul.gateway.presentation import (
    InterfaceSettingsPatch,
    PresentationContent,
    PresentationError,
    PresentationFailure,
    PresentationService,
)
from tinysoul.infra.json import JsonObject

from ..errors import EndpointRequestError


class EndpointPresentationEngine:
    def __init__(
        self, service: PresentationService, *, max_resource_bytes: int
    ) -> None:
        self._service = service
        self._max_resource_bytes = max_resource_bytes

    async def configuration(self, document_id: str) -> JsonObject:
        result = await self._call(self._service.configuration(document_id))
        return result.to_json()

    async def save_configuration(
        self, document_id: str, changes: InterfaceSettingsPatch
    ) -> JsonObject:
        result = await self._call(
            self._service.save_configuration(document_id, changes)
        )
        return result.to_json()

    async def assets(self) -> JsonObject:
        result = await self._call(self._service.assets())
        return {"items": [asset.to_json() for asset in result]}

    async def content(self, path: str) -> PresentationContent:
        return await self._call(
            self._service.content(path, max_bytes=self._max_resource_bytes)
        )

    @staticmethod
    async def _call[T](operation: Awaitable[T]) -> T:
        try:
            return await operation
        except PresentationError as exc:
            status = {
                PresentationFailure.INVALID_CONFIG: 422,
                PresentationFailure.INVALID_PATH: 422,
                PresentationFailure.NOT_FOUND: 404,
                PresentationFailure.TOO_LARGE: 413,
                PresentationFailure.IO_FAILED: 500,
            }[exc.kind]
            raise EndpointRequestError(
                status_code=status,
                code=exc.kind.value,
                message=str(exc),
                details={"field": exc.field} if exc.field else {},
            ) from exc
