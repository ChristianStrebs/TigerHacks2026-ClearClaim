"""FastAPI dependency helpers for accessing shared services and the member's data."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth import LOCAL_MEMBER, SIGN_IN_DETAIL, Member, TokenVerifier
from app.config import Settings
from app.services.gemini import GeminiService
from app.services.storage import MemberStore, SavedPlan, Storage

NO_PLAN_DETAIL = "Choose the sample plan or add your own benefits first."

_bearer = HTTPBearer(auto_error=False, description="Supabase access token")


@dataclass
class AppServices:
    settings: Settings
    gemini: GeminiService
    storage: Storage
    # None when Supabase isn't configured: everyone is the single local member.
    verifier: TokenVerifier | None = None


def get_services(request: Request) -> AppServices:
    return request.app.state.services


def current_member(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    services: AppServices = Depends(get_services),
) -> Member:
    if services.verifier is None:
        return LOCAL_MEMBER
    if credentials is None:
        raise HTTPException(
            status_code=401, detail=SIGN_IN_DETAIL, headers={"WWW-Authenticate": "Bearer"}
        )
    return services.verifier.member(credentials.credentials)


def member_store(
    member: Member = Depends(current_member),
    services: AppServices = Depends(get_services),
) -> MemberStore:
    return services.storage.for_member(member)


def require_plan(store: MemberStore) -> SavedPlan:
    saved = store.get_plan()
    if saved is None:
        raise HTTPException(status_code=409, detail=NO_PLAN_DETAIL)
    return saved
