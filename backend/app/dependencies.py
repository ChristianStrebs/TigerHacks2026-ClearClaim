"""FastAPI dependency helpers for accessing shared services."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from fastapi import HTTPException, Request

from app.config import Settings
from app.schemas import EobScanResponse
from app.services.benefits import PlanProfile
from app.services.gemini import GeminiService
from app.services.vector_store import VectorStore

NO_PLAN_DETAIL = "Choose the sample plan or add your own benefits first."
MAX_SAVED_SCANS = 5


@dataclass
class AppServices:
    settings: Settings
    gemini: GeminiService
    vector_store: VectorStore
    # Single active plan: ClearClaim is a single-member demo with no accounts.
    # None until the member picks the sample plan or submits their own.
    plan: PlanProfile | None = None
    # Newest last. In memory only: a restart or plan change forgets them.
    scans: deque[EobScanResponse] = field(default_factory=lambda: deque(maxlen=MAX_SAVED_SCANS))

    def set_plan(self, plan: PlanProfile | None) -> None:
        """Switch plans; saved scans were checked against the old plan, so drop them."""
        self.plan = plan
        self.scans.clear()

    @property
    def latest_scan(self) -> EobScanResponse | None:
        return self.scans[-1] if self.scans else None


def get_services(request: Request) -> AppServices:
    return request.app.state.services


def require_plan(services: AppServices) -> PlanProfile:
    if services.plan is None:
        raise HTTPException(status_code=409, detail=NO_PLAN_DETAIL)
    return services.plan
