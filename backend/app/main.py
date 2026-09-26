"""ClearClaim FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.dependencies import AppServices
from app.routers import chat, documents, eob, health, plan
from app.services.benefits import SAMPLE_PLAN_NAME, sample_plan
from app.services.gemini import GeminiService, GeminiUnavailableError
from app.services.indexing import index_document, load_sample_policy
from app.services.vector_store import create_vector_store

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("clearclaim")


def _seed_sample_policy(services: AppServices) -> None:
    """Index the bundled sample benefits policy so the demo works immediately."""
    text = load_sample_policy()
    try:
        added = index_document(services, SAMPLE_PLAN_NAME, text)
    except GeminiUnavailableError as exc:
        # The index must use one embedding space, so a startup failure switches the
        # whole app to demo mode rather than mixing live and offline vectors.
        services.gemini.disable(str(exc))
        added = index_document(services, SAMPLE_PLAN_NAME, text)
    logger.info("Seeded %d policy chunks into %s", added, services.vector_store.backend_name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    services = AppServices(
        settings=settings,
        gemini=GeminiService(settings),
        vector_store=create_vector_store(settings),
        plan=sample_plan(settings),
    )
    app.state.services = services
    # Only auto-seed the in-memory store; a Supabase-backed store persists across
    # restarts and should be seeded explicitly via the /api/documents endpoints.
    if services.vector_store.backend_name == "in-memory":
        _seed_sample_policy(services)
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
    return app


app = create_app()
