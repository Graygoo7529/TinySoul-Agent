"""Endpoint Workspace resource operations through the owner service."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from tinysoul.infra.json import JsonObject
from tinysoul.plugins.workspace import (
    WorkspaceBundleWrite,
    WorkspaceResourceRecord,
    WorkspaceTag,
    WorkspaceTextEdit,
)
from tinysoul.plugins.workspace.errors import (
    WorkspaceContractError,
    WorkspaceError,
    WorkspaceIOError,
    WorkspaceNotFoundError,
)
from tinysoul.plugins.workspace.services import WorkspaceService

from ..errors import EndpointRequestError
from .context import EndpointEngineContext


class EndpointWorkspaceEngine:
    """Keep Workspace leases and context synchronization in one boundary."""

    def __init__(self, context: EndpointEngineContext) -> None:
        self._context = context

    async def write_text(
        self,
        *,
        ref: str,
        text: str,
        overwrite: bool,
    ) -> JsonObject:
        try:
            async with self._context.services.registry.get(
                WorkspaceService
            ).operation() as workspace:
                record = await workspace.write_text(
                    ref,
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
        ref: str,
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
                            ref=ref,
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

    async def trash_resource(
        self,
        *,
        ref: str,
    ) -> JsonObject:
        try:
            async with self._context.services.registry.get(
                WorkspaceService
            ).operation() as workspace:
                item = await workspace.trash_resource(
                    ref,
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

    async def mkdir(self, ref: str) -> JsonObject:
        return await self._resource_change(lambda workspace: workspace.mkdir(ref))

    async def move(self, source_ref: str, target_ref: str) -> JsonObject:
        return await self._resource_change(
            lambda workspace: workspace.move(source_ref, target_ref)
        )

    async def tag(self, ref: str, tags: tuple[WorkspaceTag, ...]) -> JsonObject:
        return await self._resource_change(lambda workspace: workspace.tag(ref, tags))

    async def edit(self, ref: str, edits: tuple[WorkspaceTextEdit, ...]) -> JsonObject:
        return await self._resource_change(
            lambda workspace: workspace.edit_text(ref, edits)
        )

    async def append(self, ref: str, text: str) -> JsonObject:
        return await self._resource_change(
            lambda workspace: workspace.append_text(ref, text)
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
    if isinstance(error, WorkspaceNotFoundError):
        return EndpointRequestError(
            status_code=404,
            code="workspace.not_found",
            message="Workspace resource was not found in the requested day.",
        )
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
            "committed_refs": (
                list(error.committed_refs)
                if isinstance(error, WorkspaceIOError)
                else []
            ),
        },
    )
