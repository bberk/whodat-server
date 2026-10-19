"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_auth import router as auth_router
from app.api.routes_health import router as health_router
from app.api.routes_leagues import router as leagues_router
from app.api.schemas_auth import validation_exception_handler
from app.config import DEFAULT_SECRET_KEY, get_settings


def create_app() -> FastAPI:
    """Build and configure the FastAPI application.

    Reads settings at call time so tests can override the environment, and adds CORS for the
    configured origins (a comma-separated `CORS_ORIGINS` value).
    """
    settings = get_settings()
    if settings.env.strip().lower() not in {"local", "test"} and (
        settings.secret_key == DEFAULT_SECRET_KEY or not settings.secret_key.strip()
    ):
        raise RuntimeError(
            "SECRET_KEY must be changed from its insecure default when ENV is not 'local' or 'test'"
        )
    app = FastAPI(title="Victory Points API", version="0.0.0")
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin for origin in settings.cors_origins.split(",") if origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(leagues_router)
    return app


app = create_app()
