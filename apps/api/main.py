"""FastAPI application factory for the Synthetos API."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import NoResultFound

from apps.api.routers import (
    analysis,
    charters,
    cycles,
    discovery,
    events,
    experiment,
    health,
    jobs,
    remediation,
    skills,
    state,
)
from libs.core.config import get_settings
from libs.core.logging import get_logger, setup_logging
from libs.core.state_machine import InvalidTransitionError
from libs.storage.base import get_async_engine

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Application lifespan: initialise logging, warm up DB engine."""
    settings = get_settings()
    setup_logging(
        json_output=(settings.env != "dev"),
        log_level="DEBUG" if settings.env == "dev" else "INFO",
    )
    log.info("starting_api", env=settings.env, port=settings.api_port)

    # Create the async engine once so the connection pool is ready.
    engine = get_async_engine()
    try:
        yield
    finally:
        await engine.dispose()
        log.info("api_shutdown")


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Synthetos",
        version="0.1.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # --- Middleware ---
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.env == "dev" else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Exception handlers ---
    @app.exception_handler(InvalidTransitionError)
    async def invalid_transition_handler(
        _request: Request, exc: InvalidTransitionError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "detail": str(exc),
                "code": "invalid_transition",
            },
        )

    @app.exception_handler(NoResultFound)
    async def no_result_handler(_request: Request, _exc: NoResultFound) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": "Resource not found"},
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled_exception", error=str(exc), exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    # --- Routers ---
    # Health check at root level (no /api/v1 prefix)
    app.include_router(health.router)

    # All domain routers under /api/v1
    api_prefix = "/api/v1"
    app.include_router(charters.router, prefix=api_prefix)
    app.include_router(cycles.router, prefix=api_prefix)
    app.include_router(state.router, prefix=api_prefix)
    app.include_router(events.router, prefix=api_prefix)
    app.include_router(jobs.router, prefix=api_prefix)
    app.include_router(skills.router, prefix=api_prefix)
    app.include_router(discovery.router, prefix=api_prefix)
    app.include_router(analysis.router, prefix=api_prefix)
    app.include_router(experiment.router, prefix=api_prefix)
    app.include_router(remediation.router, prefix=api_prefix)

    return app


# Module-level app instance for ``uvicorn apps.api.main:app``
app = create_app()
