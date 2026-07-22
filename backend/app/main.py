"""Sentify API - Entry point."""

from fastapi import FastAPI

app = FastAPI(
    title="Sentify API",
    version="1.0.0",
    description="Plataforma de análisis de sentimiento para reseñas de clientes",
)

api_v1_prefix = "/api/v1"


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}
