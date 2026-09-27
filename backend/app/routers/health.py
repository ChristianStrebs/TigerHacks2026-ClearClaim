"""Health and readiness endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app import __version__
from app.dependencies import AppServices, get_services
from app.schemas import HealthResponse

router = APIRouter(tags=["system"])


@router.get("/api/health", response_model=HealthResponse)
def health(services: AppServices = Depends(get_services)) -> HealthResponse:
    settings = services.settings
    sessions = services.verifier is not None
    return HealthResponse(
        status="ok",
        version=__version__,
        gemini_enabled=services.gemini.enabled,
        supabase_enabled=sessions,
        supabase_url=settings.supabase_url.strip().rstrip("/") if sessions else None,
        supabase_publishable_key=settings.supabase_publishable_key.strip() if sessions else None,
        storage=services.storage.backend_name,
        chat_model=services.settings.gemini_chat_model,
        embed_model=services.settings.gemini_embed_model,
    )
