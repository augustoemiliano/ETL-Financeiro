"""Fábrica da aplicação FastAPI mantendo bootstrapping fora das rotinas CLI."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.health import create_health_router
from app.api.routes_etl import router as etl_router
from app.core.config import Settings, get_settings
from app.core.logging_config import configure_logging, get_logger
from app.db.session import get_engine

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings)
    get_engine(settings)
    logger = get_logger(__name__)
    logger.info("API inicializada (%s)", settings.environment)
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    application = FastAPI(
        title=settings.app_name,
        lifespan=_lifespan,
        version="1.0.0",
    )
    application.include_router(create_health_router())
    application.include_router(etl_router)

    application.mount(
        "/static",
        StaticFiles(directory=str(_STATIC_DIR)),
        name="static",
    )

    @application.get("/", include_in_schema=False)
    def dashboard_console() -> FileResponse:
        return FileResponse(
            _STATIC_DIR / "dashboard.html",
            media_type="text/html; charset=utf-8",
        )

    return application
