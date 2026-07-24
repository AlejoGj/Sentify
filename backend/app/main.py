"""Sentify API - Entry point."""

from fastapi import FastAPI

from app.api.routes.auth import router as auth_router

app = FastAPI(
    title="Sentify API",
    version="1.0.0",
    description="Plataforma de análisis de sentimiento para reseñas de clientes",
)

api_v1_prefix = "/api/v1"

# Register routers
app.include_router(auth_router, prefix=api_v1_prefix)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}
