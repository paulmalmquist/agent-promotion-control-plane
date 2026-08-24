from uuid import UUID, uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from promotion_control_plane.api.router import create_router
from promotion_control_plane.application.errors import ApplicationError
from promotion_control_plane.infrastructure.database import get_session_factory
from promotion_control_plane.logging import configure_logging
from promotion_control_plane.settings import get_settings


def _correlation_id(request: Request) -> UUID:
    value = getattr(request.state, "correlation_id", None)
    return value if isinstance(value, UUID) else uuid4()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = structlog.get_logger("promotion_api")
    app = FastAPI(
        title="Agent Promotion Control Plane API",
        version="0.1.0",
        description=(
            "Evidence-gated lifecycle decisions and asynchronous registry activation. "
            "Promotion changes which tested version new production runs select. "
            "It does not authorize a run or grant tool access."
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Idempotency-Key", "Last-Event-ID", "X-Correlation-ID"],
    )

    @app.middleware("http")
    async def correlation_middleware(request: Request, call_next: object) -> object:
        incoming = request.headers.get("X-Correlation-ID")
        try:
            correlation_id = UUID(incoming) if incoming else uuid4()
        except ValueError:
            correlation_id = uuid4()
        request.state.correlation_id = correlation_id
        response = await call_next(request)  # type: ignore[operator]
        response.headers["X-Correlation-ID"] = str(correlation_id)
        logger.info(
            "http_request_completed",
            correlation_id=str(correlation_id),
            method=request.method,
            route=request.url.path,
            status=response.status_code,
            candidate_id=request.path_params.get("candidate_id"),
            evaluation_run_id=request.path_params.get("run_id"),
            scheduled_job_id=request.path_params.get("job_id"),
            registry_operation_id=request.path_params.get("operation_id"),
        )
        return response

    @app.exception_handler(ApplicationError)
    async def application_error_handler(request: Request, error: ApplicationError) -> JSONResponse:
        return JSONResponse(
            {
                "type": f"https://agent-promotion-control-plane.local/problems/{error.code.lower()}",
                "title": error.title,
                "status": error.status,
                "detail": error.detail,
                "instance": request.url.path,
                "code": error.code,
                "correlation_id": str(_correlation_id(request)),
                "extensions": error.extensions,
            },
            status_code=error.status,
            media_type="application/problem+json",
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            {
                "type": "https://agent-promotion-control-plane.local/problems/request-validation",
                "title": "Request validation failed",
                "status": 422,
                "detail": "The request did not match the API contract.",
                "instance": request.url.path,
                "code": "REQUEST_VALIDATION_FAILED",
                "correlation_id": str(_correlation_id(request)),
                "extensions": {"errors": error.errors()},
            },
            status_code=422,
            media_type="application/problem+json",
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, error: StarletteHTTPException) -> JSONResponse:
        code = "RESOURCE_NOT_FOUND" if error.status_code == 404 else "HTTP_ERROR"
        return JSONResponse(
            {
                "type": f"https://agent-promotion-control-plane.local/problems/{code.lower()}",
                "title": "Resource not found"
                if error.status_code == 404
                else "HTTP request failed",
                "status": error.status_code,
                "detail": str(error.detail),
                "instance": request.url.path,
                "code": code,
                "correlation_id": str(_correlation_id(request)),
                "extensions": {},
            },
            status_code=error.status_code,
            media_type="application/problem+json",
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(request: Request, error: IntegrityError) -> JSONResponse:
        logger.warning(
            "database_integrity_conflict",
            correlation_id=str(_correlation_id(request)),
            route=request.url.path,
            error_type=type(error.orig).__name__,
        )
        return JSONResponse(
            {
                "type": "https://agent-promotion-control-plane.local/problems/database-conflict",
                "title": "Request conflicts with persisted state",
                "status": 409,
                "detail": "A uniqueness or relational invariant rejected this request.",
                "instance": request.url.path,
                "code": "DATABASE_INTEGRITY_CONFLICT",
                "correlation_id": str(_correlation_id(request)),
                "extensions": {},
            },
            status_code=409,
            media_type="application/problem+json",
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error_handler(request: Request, error: SQLAlchemyError) -> JSONResponse:
        logger.exception(
            "database_request_failed",
            correlation_id=str(_correlation_id(request)),
            route=request.url.path,
            error_type=type(error).__name__,
        )
        return JSONResponse(
            {
                "type": "https://agent-promotion-control-plane.local/problems/database-unavailable",
                "title": "Database request failed",
                "status": 503,
                "detail": "The control plane could not complete its database transaction.",
                "instance": request.url.path,
                "code": "DATABASE_REQUEST_FAILED",
                "correlation_id": str(_correlation_id(request)),
                "extensions": {},
            },
            status_code=503,
            media_type="application/problem+json",
        )

    @app.exception_handler(Exception)
    async def internal_error_handler(request: Request, error: Exception) -> JSONResponse:
        logger.exception(
            "unhandled_request_error",
            correlation_id=str(_correlation_id(request)),
            route=request.url.path,
            error_type=type(error).__name__,
        )
        return JSONResponse(
            {
                "type": "https://agent-promotion-control-plane.local/problems/internal-error",
                "title": "Internal request failed",
                "status": 500,
                "detail": "The control plane encountered an unexpected error.",
                "instance": request.url.path,
                "code": "INTERNAL_ERROR",
                "correlation_id": str(_correlation_id(request)),
                "extensions": {},
            },
            status_code=500,
            media_type="application/problem+json",
        )

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        with get_session_factory()() as session:
            session.execute(text("SELECT 1"))
        return {"status": "ok"}

    app.include_router(create_router())
    return app
