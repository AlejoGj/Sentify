"""Sentify API - Entry point."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes.auth import router as auth_router
from app.api.routes.batches import router as batches_router
from app.config import settings
from app.infrastructure.storage.database import init_db

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: initialize DB on startup."""
    init_db()
    yield


app = FastAPI(
    title="Sentify API",
    version="1.0.0",
    description="Plataforma de análisis de sentimiento para reseñas de clientes",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# CORS middleware — origin from env var, credentials enabled, restricted methods/headers
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.cors_allowed_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)

api_v1_prefix = "/api/v1"

# Register routers
app.include_router(auth_router, prefix=api_v1_prefix)
app.include_router(batches_router, prefix=api_v1_prefix)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Pass FastAPI/Starlette HTTP exceptions through unchanged."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch all truly unhandled exceptions.

    Logs the full stack trace so CloudWatch picks it up on Lambda,
    and returns a generic 500 so no internal details leak to callers.
    """
    logger.exception(
        "Unhandled exception on %s %s", request.method, request.url.path
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Error interno del servidor"},
    )
