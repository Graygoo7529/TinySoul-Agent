"""Endpoint Workspace resource operations through the owner service."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Awaitable, Callable

from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.plugins.workspace.services import WorkspaceService
from tinysoul.plugins.workspace import (
    WorkspaceBundleWrite,
    WorkspaceManifest,
    WorkspaceResourceRecord,
    WorkspaceTag,
    WorkspaceTextEdit,
)
from tinysoul.plugins.workspace.errors import (
    WorkspaceContractError,
    WorkspaceError,
    WorkspaceIOError,
)

from ..errors import EndpointRequestError
from .context import EndpointEngineContext


@dataclass(frozen=True)
class EndpointResourceBlob:
    link: str
    data: bytes
    media_type: str
    size: int


class EndpointWorkspaceEngine:
    """Keep Workspace leases and context synchronization in one boundary."""

    def __init__(self, context: EndpointEngineContext) -> None:
        self._context = context

    async def manifest(self) -> JsonObject:
        try:
            async with self._context.services.registry.get(
                WorkspaceService
            ).operation() as workspace:
                result = await workspace.reconcile()
                if not result.complete:
                    raise EndpointRequestError(
                        status_code=409,
                        code="workspace.reconciliation_incomplete",
                        message="Workspace reconciliation is incomplete.",
                        details=to_json_object({"skip_counts": result.skip_counts()}),
                    )
                return result.manifest.to_json()
        except EndpointRequestError:
            raise
        except WorkspaceError as exc:
            raise _workspace_error(exc) from exc

    async def read_text(self, link: str) -> JsonObject:
        try:
            async with self._context.services.registry.get(
                WorkspaceService
            ).operation() as workspace:
                read = await workspace.read_text(
                    link,
                    max_chars=self._context.settings.max_resource_chars,
                )
                return {
                    "link": read.link,
                    "text": read.text,
                    "truncated": read.truncated,
                    "size": read.size,
                }
        except WorkspaceError as exc:
            raise _workspace_error(exc) from exc

    async def read_blob(self, link: str) -> EndpointResourceBlob:
        try:
            async with self._context.services.registry.get(
                WorkspaceService
            ).operation() as workspace:
                read = await workspace.read_bytes(
                    link,
                    max_bytes=self._context.settings.max_resource_bytes,
                )
                return EndpointResourceBlob(
                    link=read.link,
                    data=read.data,
                    media_type=read.media_type,
                    size=read.size,
                )
        except WorkspaceError as exc:
            raise _workspace_error(exc) from exc

    async def write_text(
        self,
        *,
        link: str,
        text: str,
        overwrite: bool,
    ) -> JsonObject:
        try:
            async with self._context.services.registry.get(
                WorkspaceService
            ).operation() as workspace:
                record = await workspace.write_text(
                    link,
                    text,
                    overwrite=overwrite,
                )
                manifest = await workspace.load_manifest()
                return {"record": record.to_json(), "manifest": manifest.to_json()}
        except WorkspaceError as exc:
            raise _workspace_error(exc) from exc

    async def write_blob(
        self,
        *,
        link: str,
        data: bytes,
        overwrite: bool,
    ) -> JsonObject:
        if len(data) > self._context.settings.max_request_bytes:
            raise EndpointRequestError(
                status_code=413,
                code="request.too_large",
                message="Workspace blob is too large.",
            )
        try:
            async with self._context.services.registry.get(
                WorkspaceService
            ).operation() as workspace:
                result = await workspace.write_bundle(
                    (
                        WorkspaceBundleWrite(
                            link=link,
                            data=data,
                            overwrite=overwrite,
                        ),
                    ),
                )
                record = result.records[0]
                return {
                    "record": record.to_json(),
                    "manifest": result.manifest.to_json(),
                }
        except WorkspaceError as exc:
            raise _workspace_error(exc) from exc

    async def trash(self) -> JsonObject:
        try:
            async with self._context.services.registry.get(
                WorkspaceService
            ).operation() as workspace:
                return {
                    "items": [
                        {"ref": item.ref, **item.to_json()}
                        for item in await workspace.trash_items()
                    ]
                }
        except WorkspaceError as exc:
            raise _workspace_error(exc) from exc

    async def trash_resource(
        self,
        *,
        link: str,
    ) -> JsonObject:
        try:
            async with self._context.services.registry.get(
                WorkspaceService
            ).operation() as workspace:
                item = await workspace.trash_resource(
                    link,
                )
                manifest = await workspace.load_manifest()
                return {
                    "trash": {"ref": item.ref, **item.to_json()},
                    "manifest": manifest.to_json(),
                }
        except WorkspaceError as exc:
            raise _workspace_error(exc) from exc

    async def restore(
        self,
        *,
        trash_ref: str,
    ) -> JsonObject:
        try:
            async with self._context.services.registry.get(
                WorkspaceService
            ).operation() as workspace:
                record = await workspace.restore_resource(
                    trash_ref,
                )
                manifest = await workspace.load_manifest()
                return {"record": record.to_json(), "manifest": manifest.to_json()}
        except WorkspaceError as exc:
            raise _workspace_error(exc) from exc

    async def mkdir(self, link: str) -> JsonObject:
        return await self._resource_change(lambda workspace: workspace.mkdir(link))

    async def move(self, link: str, target_link: str) -> JsonObject:
        return await self._resource_change(
            lambda workspace: workspace.move(link, target_link)
        )

    async def tag(self, link: str, tags: tuple[WorkspaceTag, ...]) -> JsonObject:
        return await self._resource_change(lambda workspace: workspace.tag(link, tags))

    async def edit(self, link: str, edits: tuple[WorkspaceTextEdit, ...]) -> JsonObject:
        return await self._resource_change(
            lambda workspace: workspace.edit_text(link, edits)
        )

    async def append(self, link: str, text: str) -> JsonObject:
        return await self._resource_change(
            lambda workspace: workspace.append_text(link, text)
        )

    async def _resource_change(
        self,
        change: Callable[[WorkspaceService], Awaitable[WorkspaceResourceRecord]],
    ) -> JsonObject:
        try:
            async with self._context.services.registry.get(
                WorkspaceService
            ).operation() as workspace:
                record = await change(workspace)
                manifest = await workspace.load_manifest()
                return {"record": record.to_json(), "manifest": manifest.to_json()}
        except WorkspaceError as exc:
            raise _workspace_error(exc) from exc


def _workspace_error(error: WorkspaceError) -> EndpointRequestError:
    if isinstance(error, WorkspaceContractError):
        return EndpointRequestError(
            status_code=409,
            code="workspace.conflict",
            message="Workspace request conflicts with the current resource or is invalid.",
        )
    return EndpointRequestError(
        status_code=500,
        code="workspace.failed",
        message="Workspace operation failed.",
        details={
            "error_type": type(error).__name__,
            "committed_links": (
                list(error.committed_links)
                if isinstance(error, WorkspaceIOError)
                else []
            ),
        },
    )
