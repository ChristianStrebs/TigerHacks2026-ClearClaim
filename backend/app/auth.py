"""Identify the member behind each request from their Supabase login token."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import jwt
from fastapi import HTTPException

from app.config import Settings

logger = logging.getLogger("clearclaim.auth")

SIGN_IN_DETAIL = "Your session has expired. Refresh the page to continue."
AUTH_DOWN_DETAIL = "We can't confirm your session right now. Please try again in a moment."


@dataclass(frozen=True)
class Member:
    id: str
    # Forwarded to Supabase so row level security limits the request to this member.
    access_token: str | None


LOCAL_MEMBER = Member(id="local", access_token=None)


class TokenVerifier:
    """Checks Supabase access tokens against the project's published signing keys."""

    def __init__(self, settings: Settings, jwks: jwt.PyJWKClient | None = None) -> None:
        self._issuer = f"{settings.supabase_url.rstrip('/')}/auth/v1"
        self._jwks = jwks or jwt.PyJWKClient(
            f"{self._issuer}/.well-known/jwks.json",
            cache_keys=True,
            lifespan=600,
            timeout=settings.supabase_timeout_seconds,
        )

    def member(self, token: str) -> Member:
        """Return the signed-in member, or raise ``HTTPException`` (401 or 503)."""
        try:
            key = self._jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["ES256", "RS256"],
                audience="authenticated",
                issuer=self._issuer,
                options={"require": ["exp", "sub"]},
                # Tolerate small clock differences between this server and Supabase.
                leeway=30,
            )
        except jwt.PyJWKClientConnectionError as exc:
            logger.warning("Couldn't fetch Supabase signing keys: %s", exc)
            raise HTTPException(status_code=503, detail=AUTH_DOWN_DETAIL) from exc
        except (jwt.PyJWKClientError, jwt.InvalidTokenError) as exc:
            raise HTTPException(
                status_code=401,
                detail=SIGN_IN_DETAIL,
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        return Member(id=str(claims["sub"]), access_token=token)
