"""FastAPI dependency helpers for accessing shared services."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from app.config import Settings
from app.services.benefits import PlanProfile
from app.services.gemini import GeminiService
from app.services.vector_store import VectorStore


@dataclass
class AppServices:
    settings: Settings
    gemini: GeminiService
    vector_store: VectorStore
    # Single active plan: ClearClaim is a single-member demo with no accounts.
    plan: PlanProfile


def get_services(request: Request) -> AppServices:
    return request.app.state.services
