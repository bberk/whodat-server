"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_auth import router as auth_router
from app.api.routes_health import router as health_router
from app.config import get_settings


def create_app() -> FastAPI:
    """Build and configure the FastAPI application.

    Reads settings at call time so tests can override the environment, and adds CORS for the
    configured origins (a comma-separated `CORS_ORIGINS` value).
    """
    settings = get_settings()
    app = FastAPI(title="Victory Points API", version="0.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin for origin in settings.cors_origins.split(",") if origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router)
    app.include_router(auth_router)
    return app


app = create_app()
