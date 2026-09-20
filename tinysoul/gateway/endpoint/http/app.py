"""FastAPI application assembly for the Endpoint protocol."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from tinysoul.infra.json import JsonObject
from tinysoul.agent.errors import (
    AgentSDKError, AgentServiceStaleError, AgentQueueFullError,
    AgentTurnUnavailableError, AgentServiceUnavailableError,
    AgentClosedError,
)
from tinysoul.kernel.loop.interaction.inbox import InboxError, InboxCapacityError

from ..config import EndpointSettings
from ..engine import EndpointEngine
from ..errors import EndpointRequestError
from .auth import bearer_valid
from .errors import error_response
from .routes.configuration import register_configuration_routes
from .routes.events import register_event_routes
from .routes.health import register_health_routes
from .routes.reflection import register_reflection_routes
from .routes.runtime import register_runtime_routes
from .routes.turns import register_turn_routes
from .routes.workspace import register_workspace_routes


def create_endpoint_app(
    engine: EndpointEngine,
    settings: EndpointSettings,
) -> FastAPI:
    app = FastAPI(
        title="TinySoul Local Endpoint",
        version="2.0.0",
        docs_url=None,
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "PUT", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=[
            "X-TinySoul-Link",
            "X-TinySoul-Size",
        ],
    )

    @app.middleware("http")
    async def authenticate(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if request.method == "OPTIONS" or request.url.path == "/v2/health":
            return await call_next(request)
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                length = int(content_length)
            except ValueError:
                return error_response(
                    400,
                    "request.invalid_length",
                    "Invalid Content-Length.",
                )
            if length > settings.max_request_bytes:
                return error_response(
                    413,
                    "request.too_large",
                    "Request body is too large.",
                )
        if not bearer_valid(request.headers.get("authorization", ""), settings):
            return error_response(
                401,
                "auth.unauthorized",
                "Bearer token is required.",
            )
        return await call_next(request)

    @app.exception_handler(EndpointRequestError)
    async def endpoint_request_error(
        request: Request,
        error: EndpointRequestError,
    ) -> JSONResponse:
        return JSONResponse(status_code=error.status_code, content=error.to_json())

    @app.exception_handler(AgentSDKError)
    async def agent_service_error(
        request: Request, error: AgentSDKError
    ) -> JSONResponse:
        code = "agent.command_rejected"
        status = 409
        details: JsonObject = {"error_type": type(error).__name__}
        if isinstance(error, AgentServiceStaleError):
            code = "service.stale"
        elif isinstance(error, AgentQueueFullError):
            code = "agent.queue_full"
        elif isinstance(error, AgentClosedError):
            code = "agent.not_ready"
        elif isinstance(error, AgentTurnUnavailableError):
            code, status = "turn.resource_not_found", 404
        elif isinstance(error, AgentServiceUnavailableError):
            code = "service.unavailable"
            details.update(module=error.module, kind=error.kind)
        return error_response(status, code, "Agent could not accept this operation.", details)

    @app.exception_handler(InboxError)
    async def inbox_error(request: Request, error: InboxError) -> JSONResponse:
        return error_response(
            409,
            "turn.inbox_full" if isinstance(error, InboxCapacityError) else "turn.command_rejected",
            "Turn could not accept this input or waiting decision.",
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        return error_response(
            422,
            "request.invalid",
            "Request does not match the Endpoint contract.",
        )

    @app.exception_handler(Exception)
    async def unexpected_error(
        request: Request,
        error: Exception,
    ) -> JSONResponse:
        return error_response(
            500,
            "endpoint.internal",
            "Endpoint request failed.",
            {"error_type": type(error).__name__},
        )

    register_health_routes(app)
    register_runtime_routes(app, engine)
    register_turn_routes(app, engine)
    register_reflection_routes(app, engine)
    register_event_routes(app, engine, settings)
    register_configuration_routes(app, engine)
    register_workspace_routes(app, engine)
    return app
