"""FastAPI application assembly for the Endpoint protocol."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from tinysoul.agent.errors import (
    AgentClosedError,
    AgentQueueFullError,
    AgentSDKError,
    AgentServiceStaleError,
    AgentServiceUnavailableError,
    AgentTurnUnavailableError,
)
from tinysoul.infra.continuation import ContinuationError
from tinysoul.infra.json import JsonObject
from tinysoul.infra.references import ReferenceError
from tinysoul.infra.time import CalendarDayError
from tinysoul.kernel.context.errors import ContextInspectRequestError
from tinysoul.kernel.interaction import QuestionError
from tinysoul.kernel.jobs.failures import JobError, JobRequestError
from tinysoul.kernel.loop.interaction.inbox import InboxCapacityError, InboxError
from tinysoul.kernel.retrieval.contracts import SearchFailure, SearchFailureKind
from tinysoul.plugins.capabilities.expand.failures import ExpandRequestError
from tinysoul.plugins.home.errors import (
    AgentHomeContractError,
    AgentHomeError,
    AgentHomeNotFoundError,
)
from tinysoul.plugins.memory.errors import (
    MemoryContractError,
    MemoryError,
    MemoryNotFoundError,
)
from tinysoul.plugins.session.errors import SessionInspectRequestError
from tinysoul.plugins.workspace.errors import WorkspaceError

from ..config import EndpointSettings
from ..engine import EndpointEngine
from ..engine.workspace import _workspace_error
from ..errors import EndpointRequestError
from .auth import bearer_valid
from .errors import error_response
from .routes.configuration import register_configuration_routes
from .routes.events import register_event_routes
from .routes.health import register_health_routes
from .routes.inspection import register_inspection_routes
from .routes.reflection import register_reflection_routes
from .routes.resources import register_resource_routes
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
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Range"],
        expose_headers=[
            "X-TinySoul-Ref",
            "X-TinySoul-Size",
            "Content-Range",
            "Accept-Ranges",
            "Content-Length",
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
            status = 503
            if error.kind == "context.unavailable":
                code, status = error.kind, 409
            elif error.kind == "resource.unresolved_origin":
                code, status = error.kind, 422
        return error_response(
            status, code, "Agent could not accept this operation.", details
        )

    @app.exception_handler(InboxError)
    async def inbox_error(request: Request, error: InboxError) -> JSONResponse:
        return error_response(
            409,
            "turn.inbox_full"
            if isinstance(error, InboxCapacityError)
            else "turn.command_rejected",
            "Turn could not accept this input or waiting decision.",
        )

    @app.exception_handler(QuestionError)
    async def question_error(request: Request, error: QuestionError) -> JSONResponse:
        return error_response(
            422, "turn.invalid_answer", "Answer does not match the question protocol."
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

    @app.exception_handler(ContinuationError)
    async def continuation_error(
        request: Request, error: ContinuationError
    ) -> JSONResponse:
        status = (
            422
            if error.reason.value in {"invalid_limit", "page_budget_too_small"}
            else 409
        )
        return error_response(status, error.reason.value, str(error), error.constraint)

    @app.exception_handler(SearchFailure)
    async def search_error(request: Request, error: SearchFailure) -> JSONResponse:
        status = (
            409
            if error.kind is SearchFailureKind.VIEW_EXPIRED
            else 503
            if error.kind is SearchFailureKind.SOURCE_UNAVAILABLE
            else 422
        )
        return error_response(
            status,
            f"search.{error.kind.value}",
            str(error),
            {"step": error.step} if error.step else {},
        )

    @app.exception_handler(AgentHomeError)
    @app.exception_handler(MemoryError)
    async def resource_error(
        request: Request, error: AgentHomeError | MemoryError
    ) -> JSONResponse:
        missing = isinstance(error, (AgentHomeNotFoundError, MemoryNotFoundError))
        invalid = isinstance(error, (AgentHomeContractError, MemoryContractError))
        return error_response(
            404 if missing else 422 if invalid else 503,
            "resource.not_found"
            if missing
            else "resource.invalid"
            if invalid
            else "resource.unavailable",
            "Resource is unavailable in the requested owner view.",
            {"error_type": type(error).__name__},
        )

    @app.exception_handler(WorkspaceError)
    async def workspace_error(request: Request, error: WorkspaceError) -> JSONResponse:
        mapped = _workspace_error(error)
        return JSONResponse(status_code=mapped.status_code, content=mapped.to_json())

    @app.exception_handler(JobError)
    async def job_error(request: Request, error: JobError) -> JSONResponse:
        return error_response(
            404 if isinstance(error, JobRequestError) else 503,
            "job.unavailable",
            "Job is unavailable in this Turn.",
        )

    @app.exception_handler(ExpandRequestError)
    async def expand_error(request: Request, error: ExpandRequestError) -> JSONResponse:
        return error_response(422, f"expand.{error.reason.value}", str(error))

    @app.exception_handler(CalendarDayError)
    async def day_error(request: Request, error: CalendarDayError) -> JSONResponse:
        return error_response(422, "day.invalid", "Day must use YYYY-MM-DD.")

    @app.exception_handler(ReferenceError)
    async def reference_error(request: Request, error: ReferenceError) -> JSONResponse:
        return error_response(422, "resource.invalid_reference", str(error))

    @app.exception_handler(ContextInspectRequestError)
    @app.exception_handler(SessionInspectRequestError)
    async def inspect_error(
        request: Request, error: ContextInspectRequestError | SessionInspectRequestError
    ) -> JSONResponse:
        return error_response(
            404 if error.reason.value == "unknown_ref" else 422,
            error.reason.value,
            str(error),
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
    register_inspection_routes(app, engine)
    register_resource_routes(app, engine)
    return app
