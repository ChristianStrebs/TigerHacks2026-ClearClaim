"""ClearClaim FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from importlib import resources

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.dependencies import AppServices
from app.routers import chat, documents, eob, health
from app.services.gemini import GeminiService, GeminiUnavailableError
from app.services.ingestion import chunk_text
from app.services.vector_store import Chunk, create_vector_store

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("clearclaim")


def _seed_sample_policy(services: AppServices) -> None:
    """Index the bundled sample benefits policy so the demo works immediately."""
    try:
        text = resources.files("app.data").joinpath("sample_policy.txt").read_text()
    except FileNotFoundError:
        logger.warning("Sample policy not found; skipping seed.")
        return
    chunks = chunk_text(text)
    try:
        embeddings = services.gemini.embed_texts(chunks)
    except GeminiUnavailableError as exc:
        # The index must use one embedding space, so a startup failure switches the
        # whole app to demo mode rather than mixing live and offline vectors.
        services.gemini.disable(str(exc))
        embeddings = services.gemini.embed_texts(chunks)
    records = [
        Chunk(document="ACME Corp Health Plan (2026)", text=c, embedding=e)
        for c, e in zip(chunks, embeddings, strict=True)
    ]
    added = services.vector_store.add(records)
    logger.info("Seeded %d policy chunks into %s", added, services.vector_store.backend_name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    services = AppServices(
        settings=settings,
        gemini=GeminiService(settings),
        vector_store=create_vector_store(settings),
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
    return app


app = create_app()
