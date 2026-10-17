"""Project presentation settings and authenticated asset reads."""

from urllib.parse import quote

from fastapi import FastAPI
from starlette.responses import Response

from ...engine import EndpointEngine
from ..schemas import (
    PresentationAssetsResponse,
    PresentationConfigResponse,
    PresentationPatchRequest,
)


def register_presentation_routes(app: FastAPI, engine: EndpointEngine) -> None:
    @app.get(
        "/v2/presentation/configs/{document_id}",
        response_model=PresentationConfigResponse,
    )
    async def configuration(document_id: str):
        return await engine.presentation.configuration(document_id)

    @app.patch(
        "/v2/presentation/configs/{document_id}",
        response_model=PresentationConfigResponse,
    )
    async def save_configuration(document_id: str, body: PresentationPatchRequest):
        return await engine.presentation.save_configuration(
            document_id, body.changes.to_patch()
        )

    @app.get("/v2/presentation/assets", response_model=PresentationAssetsResponse)
    async def assets():
        return await engine.presentation.assets()

    @app.get(
        "/v2/presentation/assets/content",
        response_class=Response,
        responses={
            200: {
                "content": {
                    "application/octet-stream": {
                        "schema": {"type": "string", "format": "binary"}
                    }
                }
            }
        },
    )
    async def content(path: str):
        result = await engine.presentation.content(path)
        filename = quote(path.replace("\\", "/").rsplit("/", 1)[-1], safe="")
        return Response(
            content=result.data,
            media_type=result.media_type,
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
                "Cache-Control": "no-store",
            },
        )
