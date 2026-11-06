"""FastAPI entry point for taskboard4-api."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from . import __version__
from .db import Database, DatabaseUnavailable
from .logging_config import configure_logging
from .metrics import MetricsMiddleware
from .settings import MissingSetting, load_database_url
from .tasks.api import router as tasks_router
from .tracing import configure_tracing, tracing_enabled

configure_logging(level=os.environ.get("LOG_LEVEL", "INFO"))
if tracing_enabled():
    configure_tracing()

logger = structlog.get_logger()


class HealthResponse(BaseModel):
    status: str


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create the `Database` (no connection attempt); refuse to start without DATABASE_URL."""
    try:
        url = load_database_url()
    except MissingSetting as exc:
        logger.error("config_missing", variable="DATABASE_URL", message=str(exc))
        raise
    db = Database(url)
    app.state.db = db
    try:
        yield
    finally:
        db.close()


def _operation(request: Request) -> str:
    if request.url.path == "/ready":
        return "ready"
    return "add" if request.method == "POST" else "list"


def create_app() -> FastAPI:
    application = FastAPI(title="taskboard4-api", version=__version__, lifespan=lifespan)
    application.add_middleware(MetricsMiddleware)
    application.include_router(tasks_router)

    @application.exception_handler(DatabaseUnavailable)
    async def _database_unavailable(request: Request, exc: Exception) -> JSONResponse:
        reason = getattr(exc, "reason", "connection")
        logger.warning("database_unavailable", operation=_operation(request), reason=reason)
        return JSONResponse(status_code=503, content={"detail": "database unavailable"})

    @application.exception_handler(Exception)
    async def _internal_error(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": "internal server error"})

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        """Liveness probe: 200 as long as the process is responding; database-free."""
        return HealthResponse(status="ok")

    @application.get("/ready", response_model=HealthResponse)
    def ready(request: Request) -> Response:
        """Readiness probe: 200 when `SELECT 1` succeeds, else 503."""
        db = getattr(request.app.state, "db", None)
        if db is None:
            reason = "not_initialized"
        elif db.ping():
            return JSONResponse(status_code=200, content={"status": "ready"})
        else:
            reason = "ping_failed"
        logger.warning("database_unavailable", operation="ready", reason=reason)
        return JSONResponse(status_code=503, content={"status": "not ready"})

    @application.get("/ping")
    def ping() -> dict[str, str]:
        """Simple ping endpoint."""
        return {"pong": "taskboard4-api"}

    @application.get("/metrics")
    def metrics() -> Response:
        """Prometheus scrape endpoint."""
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return application


app = create_app()
