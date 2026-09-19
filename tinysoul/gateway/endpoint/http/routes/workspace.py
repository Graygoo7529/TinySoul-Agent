"""Workspace manifest, resource and trash routes."""

from __future__ import annotations

from fastapi import Body, FastAPI, Query
from starlette.responses import Response

from tinysoul.infra.json import JsonObject
from tinysoul.plugins.workspace import WorkspaceTextEdit
from ..schemas.workspace import (
    WorkspaceDirectoryRequest,
    WorkspaceMoveRequest,
    WorkspaceTagRequest,
    WorkspaceEditRequest,
    WorkspaceAppendRequest,
)

from ...engine import EndpointEngine
from ..schemas import (
    WorkspaceRestoreRequest,
    WorkspaceTrashRequest,
    WorkspaceWriteRequest,
)


def register_workspace_routes(app: FastAPI, engine: EndpointEngine) -> None:
    @app.post("/v1/workspace/directory")
    async def workspace_directory(body: WorkspaceDirectoryRequest) -> JsonObject:
        return await engine.workspace.mkdir(body.link)

    @app.post("/v1/workspace/move")
    async def workspace_move(body: WorkspaceMoveRequest) -> JsonObject:
        return await engine.workspace.move(body.link, body.target_link)

    @app.put("/v1/workspace/tags")
    async def workspace_tags(body: WorkspaceTagRequest) -> JsonObject:
        return await engine.workspace.tag(body.link, tuple(body.tags))

    @app.post("/v1/workspace/edit")
    async def workspace_edit(body: WorkspaceEditRequest) -> JsonObject:
        return await engine.workspace.edit(
            body.link,
            tuple(
                WorkspaceTextEdit(item.old_text, item.new_text) for item in body.edits
            ),
        )

    @app.post("/v1/workspace/append")
    async def workspace_append(body: WorkspaceAppendRequest) -> JsonObject:
        return await engine.workspace.append(body.link, body.text)

    @app.get("/v1/workspace/manifest")
    async def workspace_manifest() -> JsonObject:
        return await engine.workspace.manifest()

    @app.get("/v1/workspace/resource")
    async def workspace_resource(link: str = Query(min_length=1)) -> JsonObject:
        return await engine.workspace.read_text(link)

    @app.get("/v1/workspace/blob")
    async def workspace_blob(link: str = Query(min_length=1)) -> Response:
        blob = await engine.workspace.read_blob(link)
        return Response(
            content=blob.data,
            media_type=blob.media_type,
            headers={
                "X-TinySoul-Link": blob.link,
                "X-TinySoul-Size": str(blob.size),
            },
        )

    @app.put("/v1/workspace/resource")
    async def write_workspace_resource(body: WorkspaceWriteRequest) -> JsonObject:
        return await engine.workspace.write_text(
            link=body.link,
            text=body.text,
            overwrite=body.overwrite,
        )

    @app.put("/v1/workspace/blob")
    async def write_workspace_blob(
        body: bytes = Body(media_type="application/octet-stream"),
        link: str = Query(min_length=1),
        overwrite: bool = Query(default=False),
    ) -> JsonObject:
        return await engine.workspace.write_blob(
            link=link,
            data=body,
            overwrite=overwrite,
        )

    @app.get("/v1/workspace/trash")
    async def workspace_trash() -> JsonObject:
        return await engine.workspace.trash()

    @app.post("/v1/workspace/trash")
    async def trash_workspace_resource(body: WorkspaceTrashRequest) -> JsonObject:
        return await engine.workspace.trash_resource(
            link=body.link,
        )

    @app.post("/v1/workspace/restore")
    async def restore_workspace_resource(body: WorkspaceRestoreRequest) -> JsonObject:
        return await engine.workspace.restore(
            trash_ref=body.trash_ref,
        )
