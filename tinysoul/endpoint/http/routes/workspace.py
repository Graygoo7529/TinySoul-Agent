"""Workspace manifest, resource and trash routes."""

from __future__ import annotations

from fastapi import Body, FastAPI, Query
from starlette.responses import Response

from tinysoul.infra.json import JsonObject
from tinysoul.workspace import WorkspaceRetention

from ...engine import EndpointEngine
from ..schemas import (
    WorkspaceRestoreRequest,
    WorkspaceTrashRequest,
    WorkspaceWriteRequest,
)


def register_workspace_routes(app: FastAPI, engine: EndpointEngine) -> None:
    @app.get("/v1/workspace/manifest")
    def workspace_manifest() -> JsonObject:
        return engine.workspace.manifest()

    @app.get("/v1/workspace/resource")
    def workspace_resource(link: str = Query(min_length=1)) -> JsonObject:
        return engine.workspace.read_text(link)

    @app.get("/v1/workspace/blob")
    def workspace_blob(link: str = Query(min_length=1)) -> Response:
        blob = engine.workspace.read_blob(link)
        return Response(
            content=blob.data,
            media_type=blob.media_type,
            headers={
                "X-TinySoul-Link": blob.link,
                "X-TinySoul-Digest": blob.digest,
                "X-TinySoul-Size": str(blob.size),
            },
        )

    @app.put("/v1/workspace/resource")
    def write_workspace_resource(body: WorkspaceWriteRequest) -> JsonObject:
        return engine.workspace.write_text(
            link=body.link,
            text=body.text,
            overwrite=body.overwrite,
            expected_digest=body.expected_digest,
            expected_revision=body.expected_revision,
            retention=_retention(body.retention),
        )

    @app.put("/v1/workspace/blob")
    def write_workspace_blob(
        body: bytes = Body(media_type="application/octet-stream"),
        link: str = Query(min_length=1),
        overwrite: bool = Query(default=False),
        expected_digest: str = Query(default=""),
        expected_revision: int = Query(ge=0),
        retention: WorkspaceRetention | None = Query(default=None),
    ) -> JsonObject:
        return engine.workspace.write_blob(
            link=link,
            data=body,
            overwrite=overwrite,
            expected_digest=expected_digest,
            expected_revision=expected_revision,
            retention=retention,
        )

    @app.get("/v1/workspace/trash")
    def workspace_trash() -> JsonObject:
        return engine.workspace.trash()

    @app.post("/v1/workspace/trash")
    def trash_workspace_resource(body: WorkspaceTrashRequest) -> JsonObject:
        return engine.workspace.trash_resource(
            link=body.link,
            expected_digest=body.expected_digest,
            expected_revision=body.expected_revision,
        )

    @app.post("/v1/workspace/restore")
    def restore_workspace_resource(body: WorkspaceRestoreRequest) -> JsonObject:
        return engine.workspace.restore(
            trash_ref=body.trash_ref,
            expected_revision=body.expected_revision,
        )


def _retention(value: str | None) -> WorkspaceRetention | None:
    return WorkspaceRetention(value) if value is not None else None
