"""Workspace manifest, resource and trash routes."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import AbstractAsyncContextManager

from fastapi import Body, FastAPI, Query, Request
from starlette.responses import Response, StreamingResponse
from starlette.types import Receive, Scope, Send

from tinysoul.infra.json import JsonObject
from tinysoul.infra.paging import PageOptions
from tinysoul.infra.time import CalendarDay
from tinysoul.plugins.workspace import WorkspaceTextEdit
from tinysoul.plugins.workspace.inspection.models import WorkspaceBlobRead

from ...engine import EndpointEngine
from ..schemas import (
    WorkspaceRestoreRequest,
    WorkspaceTrashRequest,
    WorkspaceWriteRequest,
)
from ..schemas.workspace import (
    WorkspaceAppendRequest,
    WorkspaceDirectoryRequest,
    WorkspaceEditRequest,
    WorkspaceMoveRequest,
    WorkspaceTagRequest,
)


def register_workspace_routes(app: FastAPI, engine: EndpointEngine) -> None:
    @app.post("/v2/workspace/directory")
    async def workspace_directory(body: WorkspaceDirectoryRequest) -> JsonObject:
        return await engine.workspace.mkdir(body.link)

    @app.post("/v2/workspace/move")
    async def workspace_move(body: WorkspaceMoveRequest) -> JsonObject:
        return await engine.workspace.move(body.link, body.target_link)

    @app.put("/v2/workspace/tags")
    async def workspace_tags(body: WorkspaceTagRequest) -> JsonObject:
        return await engine.workspace.tag(body.link, tuple(body.tags))

    @app.post("/v2/workspace/edit")
    async def workspace_edit(body: WorkspaceEditRequest) -> JsonObject:
        return await engine.workspace.edit(
            body.link,
            tuple(
                WorkspaceTextEdit(item.old_text, item.new_text) for item in body.edits
            ),
        )

    @app.post("/v2/workspace/append")
    async def workspace_append(body: WorkspaceAppendRequest) -> JsonObject:
        return await engine.workspace.append(body.link, body.text)

    @app.get("/v2/workspace/manifest")
    async def workspace_manifest(day: str | None = None) -> JsonObject:
        return await engine.inspection.workspace_manifest(
            CalendarDay.parse(day) if day else None
        )

    @app.get("/v2/workspace/resource")
    async def workspace_resource(
        link: str = Query(min_length=1),
        day: str | None = None,
        continuation: str | None = None,
        max_chars: int = 16000,
        full: bool = False,
    ) -> JsonObject:
        return await engine.inspection.workspace_text(
            link,
            CalendarDay.parse(day) if day else None,
            page=PageOptions(continuation, max_chars=max_chars),
            full=full,
        )

    @app.get("/v2/workspace/blob")
    async def workspace_blob(
        request: Request, link: str = Query(min_length=1), day: str | None = None
    ) -> Response:
        return WorkspaceBlobResponse(
            engine.inspection.workspace_blob(
                link, CalendarDay.parse(day) if day else None
            ),
            request.headers.get("range"),
        )

    @app.put("/v2/workspace/resource")
    async def write_workspace_resource(body: WorkspaceWriteRequest) -> JsonObject:
        return await engine.workspace.write_text(
            link=body.link,
            text=body.text,
            overwrite=body.overwrite,
        )

    @app.put("/v2/workspace/blob")
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

    @app.get("/v2/workspace/trash")
    async def workspace_trash(
        day: str | None = None, continuation: str | None = None, limit: int = 30
    ) -> JsonObject:
        return await engine.inspection.workspace_trash(
            CalendarDay.parse(day) if day else None, PageOptions(continuation, limit)
        )

    @app.post("/v2/workspace/trash")
    async def trash_workspace_resource(body: WorkspaceTrashRequest) -> JsonObject:
        return await engine.workspace.trash_resource(
            link=body.link,
        )

    @app.post("/v2/workspace/restore")
    async def restore_workspace_resource(body: WorkspaceRestoreRequest) -> JsonObject:
        return await engine.workspace.restore(
            trash_ref=body.trash_ref,
        )


class WorkspaceBlobResponse(Response):
    def __init__(
        self,
        source: AbstractAsyncContextManager[WorkspaceBlobRead],
        range_header: str | None,
    ) -> None:
        super().__init__()
        self._source, self._range = source, range_header

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async with self._source as blob:
            start, stop, status = 0, blob.size, 200
            if self._range:
                bounds = _byte_range(self._range, blob.size)
                if bounds is None:
                    await Response(
                        status_code=416,
                        headers={"Content-Range": f"bytes */{blob.size}"},
                    )(scope, receive, send)
                    return
                start, stop = bounds
                status = 206
            headers = {
                "Accept-Ranges": "bytes",
                "Content-Length": str(stop - start),
                "X-TinySoul-Size": str(blob.size),
            }
            if blob.link.isascii():
                headers["X-TinySoul-Link"] = blob.link
            if status == 206:
                headers["Content-Range"] = f"bytes {start}-{stop - 1}/{blob.size}"

            def chunks() -> Iterator[bytes]:
                blob.stream.seek(start)
                remaining = stop - start
                while remaining:
                    chunk = blob.stream.read(min(65536, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

            await StreamingResponse(
                chunks(),
                status_code=status,
                media_type=blob.media_type,
                headers=headers,
            )(scope, receive, send)


def _byte_range(value: str, size: int) -> tuple[int, int] | None:
    match = re.fullmatch(r"bytes=([0-9]{0,20})-([0-9]{0,20})", value)
    if match is None:
        return None
    first, last = match.groups()
    if not (first or last):
        return None
    start = int(first) if first else max(0, size - int(last))
    stop = min(size, int(last) + 1) if first and last else size
    return (start, stop) if 0 <= start < stop <= size else None
