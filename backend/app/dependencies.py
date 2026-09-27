"""FastAPI dependency helpers for accessing shared services."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request

from app.config import Settings
from app.services.benefits import PlanProfile
from app.services.gemini import GeminiService
from app.services.vector_store import VectorStore

NO_PLAN_DETAIL = "Choose the sample plan or add your own benefits first."


@dataclass
class AppServices:
    settings: Settings
    gemini: GeminiService
    vector_store: VectorStore
    # Single active plan: ClearClaim is a single-member demo with no accounts.
    # None until the member picks the sample plan or submits their own.
    plan: PlanProfile | None = None


def get_services(request: Request) -> AppServices:
    return request.app.state.services


def require_plan(services: AppServices) -> PlanProfile:
    if services.plan is None:
        raise HTTPException(status_code=409, detail=NO_PLAN_DETAIL)
    return services.plan
