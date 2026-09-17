"""Endpoint Workspace resource and CAS operation engine."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.agent.errors import AgentSDKError
from tinysoul.plugins.workspace.services import WorkspaceService
from tinysoul.plugins.workspace import (
    WorkspaceBundleWrite,
    WorkspaceManifest,
    WorkspaceRetention,
)
from tinysoul.plugins.workspace.errors import WorkspaceContractError, WorkspaceError

from ..errors import EndpointRequestError
from .context import EndpointEngineContext


@dataclass(frozen=True)
class EndpointResourceBlob:
    link: str
    data: bytes
    media_type: str
    size: int
    digest: str


class EndpointWorkspaceEngine:
    """Keep Workspace leases, CAS and context synchronization in one boundary."""

    def __init__(self, context: EndpointEngineContext) -> None:
        self._context = context

    async def manifest(self) -> JsonObject:
        try:
            async with self._context.services.registry.get(WorkspaceService).operation() as workspace:
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
        except AgentSDKError as exc:
            raise _not_ready(exc) from exc
        except WorkspaceError as exc:
            raise _workspace_error(exc) from exc

    async def read_text(self, link: str) -> JsonObject:
        try:
            async with self._context.services.registry.get(WorkspaceService).operation() as workspace:
                read = await workspace.read_text(
                    link,
                    max_chars=self._context.settings.max_resource_chars,
                )
                return {
                    "link": read.link,
                    "text": read.text,
                    "truncated": read.truncated,
                    "size": read.size,
                    "digest": read.digest,
                }
        except AgentSDKError as exc:
            raise _not_ready(exc) from exc
        except WorkspaceError as exc:
            raise _workspace_error(exc) from exc

    async def read_blob(self, link: str) -> EndpointResourceBlob:
        try:
            async with self._context.services.registry.get(WorkspaceService).operation() as workspace:
                read = await workspace.read_bytes(
                    link,
                    max_bytes=self._context.settings.max_resource_bytes,
                )
                return EndpointResourceBlob(
                    link=read.link,
                    data=read.data,
                    media_type=read.media_type,
                    size=read.size,
                    digest=read.digest,
                )
        except AgentSDKError as exc:
            raise _not_ready(exc) from exc
        except WorkspaceError as exc:
            raise _workspace_error(exc) from exc

    async def write_text(
        self,
        *,
        link: str,
        text: str,
        overwrite: bool,
        expected_digest: str,
        expected_revision: int,
        retention: WorkspaceRetention | None,
    ) -> JsonObject:
        try:
            async with self._context.services.registry.get(WorkspaceService).operation() as workspace:
                record = await workspace.write_text(
                    link,
                    text,
                    overwrite=overwrite,
                    expected_digest=expected_digest,
                    expected_revision=expected_revision,
                    retention=retention,
                )
                manifest = await workspace.load_manifest()
                self._sync_workspace_change(manifest)
                return {"record": record.to_json(), "manifest": manifest.to_json()}
        except AgentSDKError as exc:
            raise _not_ready(exc) from exc
        except WorkspaceError as exc:
            raise _workspace_error(exc) from exc

    async def write_blob(
        self,
        *,
        link: str,
        data: bytes,
        overwrite: bool,
        expected_digest: str,
        expected_revision: int,
        retention: WorkspaceRetention | None,
    ) -> JsonObject:
        if len(data) > self._context.settings.max_request_bytes:
            raise EndpointRequestError(
                status_code=413,
                code="request.too_large",
                message="Workspace blob is too large.",
            )
        try:
            async with self._context.services.registry.get(WorkspaceService).operation() as workspace:
                result = await workspace.write_bundle(
                    (
                        WorkspaceBundleWrite(
                            link=link,
                            data=data,
                            overwrite=overwrite,
                            expected_digest=expected_digest,
                            retention=retention,
                        ),
                    ),
                    expected_revision=expected_revision,
                )
                record = result.records[0]
                self._sync_workspace_change(result.manifest)
                return {
                    "record": record.to_json(),
                    "manifest": result.manifest.to_json(),
                }
        except AgentSDKError as exc:
            raise _not_ready(exc) from exc
        except WorkspaceError as exc:
            raise _workspace_error(exc) from exc

    async def trash(self) -> JsonObject:
        try:
            async with self._context.services.registry.get(WorkspaceService).operation() as workspace:
                return {
                    "items": [
                        {"ref": item.ref, **item.to_json()}
                        for item in await workspace.trash_items()
                    ]
                }
        except AgentSDKError as exc:
            raise _not_ready(exc) from exc
        except WorkspaceError as exc:
            raise _workspace_error(exc) from exc

    async def trash_resource(
        self,
        *,
        link: str,
        expected_digest: str,
        expected_revision: int,
    ) -> JsonObject:
        try:
            async with self._context.services.registry.get(WorkspaceService).operation() as workspace:
                item = await workspace.trash_resource(
                    link,
                    reason="endpoint.delete",
                    expected_digest=expected_digest,
                    expected_revision=expected_revision,
                )
                manifest = await workspace.load_manifest()
                self._sync_workspace_change(manifest)
                return {
                    "trash": {"ref": item.ref, **item.to_json()},
                    "manifest": manifest.to_json(),
                }
        except AgentSDKError as exc:
            raise _not_ready(exc) from exc
        except WorkspaceError as exc:
            raise _workspace_error(exc) from exc

    async def restore(
        self,
        *,
        trash_ref: str,
        expected_revision: int,
    ) -> JsonObject:
        try:
            async with self._context.services.registry.get(WorkspaceService).operation() as workspace:
                record = await workspace.restore_resource(
                    trash_ref,
                    expected_revision=expected_revision,
                )
                manifest = await workspace.load_manifest()
                self._sync_workspace_change(manifest)
                return {"record": record.to_json(), "manifest": manifest.to_json()}
        except AgentSDKError as exc:
            raise _not_ready(exc) from exc
        except WorkspaceError as exc:
            raise _workspace_error(exc) from exc

    def _sync_workspace_change(self, manifest: WorkspaceManifest) -> None:
        self._context.gateway.sync_workspace_context(
            manifest,
            source="endpoint.workspace",
        )


def _not_ready(error: Exception) -> EndpointRequestError:
    return EndpointRequestError(
        status_code=409,
        code="program.not_ready",
        message="TinySoul active day is not ready.",
        details={"error_type": type(error).__name__},
    )


def _workspace_error(error: WorkspaceError) -> EndpointRequestError:
    if isinstance(error, WorkspaceContractError):
        return EndpointRequestError(
            status_code=409,
            code="workspace.conflict",
            message=str(error),
        )
    return EndpointRequestError(
        status_code=500,
        code="workspace.failed",
        message="Workspace operation failed.",
        details={"error_type": type(error).__name__},
    )
