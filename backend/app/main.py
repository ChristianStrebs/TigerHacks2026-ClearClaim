"""ClearClaim FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.dependencies import AppServices
from app.routers import chat, documents, eob, health, plan, samples
from app.services.gemini import GeminiService, GeminiUnavailableError
from app.services.vector_store import create_vector_store

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("clearclaim")


def _check_embeddings(services: AppServices) -> None:
    """Pick live or offline embeddings once, before anything is indexed."""
    if not services.gemini.enabled:
        return
    try:
        services.gemini.embed_query("ClearClaim startup check")
    except GeminiUnavailableError as exc:
        # The index must use one embedding space, so a startup failure switches the
        # whole app to demo mode rather than mixing live and offline vectors.
        services.gemini.disable(str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    services = AppServices(
        settings=settings,
        gemini=GeminiService(settings),
        vector_store=create_vector_store(settings),
    )
    app.state.services = services
    _check_embeddings(services)
    logger.info("Ready; waiting for the member to choose the sample plan or their own")
    yield


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
    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(documents.router)
    app.include_router(eob.router)
    app.include_router(plan.router)
    app.include_router(samples.router)
    return app


app = create_app()
