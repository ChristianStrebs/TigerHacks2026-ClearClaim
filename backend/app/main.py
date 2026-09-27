"""ClearClaim FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.auth import TokenVerifier
from app.config import get_settings
from app.dependencies import AppServices
from app.routers import chat, eob, health, plan, samples
from app.services.gemini import GeminiService, GeminiUnavailableError
from app.services.storage import StorageError, create_storage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("clearclaim")

STORAGE_DOWN_DETAIL = "We couldn't reach your saved data. Please try again in a moment."


def _check_embeddings(services: AppServices) -> None:
    """Pick live or offline embeddings once, before anything is indexed."""
    if not services.gemini.enabled:
        return
    try:
        services.gemini.embed_query("ClearClaim startup check")
    except GeminiUnavailableError as exc:
        # Vectors from different spaces can't be compared, so a startup failure switches
        # the whole app to demo mode rather than mixing live and offline vectors.
        services.gemini.disable(str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    services = AppServices(
        settings=settings,
        gemini=GeminiService(settings),
        storage=create_storage(settings),
        verifier=TokenVerifier(settings) if settings.supabase_enabled else None,
    )
    app.state.services = services
    _check_embeddings(services)
    logger.info(
        "Ready with %s storage; waiting for members to choose a plan",
        services.storage.backend_name,
    )
    try:
        yield
    finally:
        services.storage.close()


async def _storage_unavailable(_request: Request, exc: Exception) -> JSONResponse:
    logger.error("Storage request failed: %s", exc)
    return JSONResponse(status_code=503, content={"detail": STORAGE_DOWN_DETAIL})


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="ClearClaim API",
        version="0.1.0",
        description="AI-powered healthcare benefits copilot.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_exception_handler(StorageError, _storage_unavailable)
    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(eob.router)
    app.include_router(plan.router)
    app.include_router(samples.router)
    return app


app = create_app()
