"""Members are identified by their Supabase access token when Supabase is configured."""

from __future__ import annotations

import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import SIGN_IN_DETAIL, TokenVerifier
from app.config import Settings, get_settings
from app.main import create_app

PROJECT = "https://example.supabase.co"
SETTINGS = Settings(SUPABASE_URL=PROJECT, SUPABASE_PUBLISHABLE_KEY="sb_publishable_test")
SIGNING_KEY = ec.generate_private_key(ec.SECP256R1())


class _FakeJwks:
    """Stands in for the project's /.well-known/jwks.json."""

    def __init__(self, public_key: ec.EllipticCurvePublicKey) -> None:
        self._public_key = public_key

    def get_signing_key_from_jwt(self, _token: str) -> SimpleNamespace:
        return SimpleNamespace(key=self._public_key)


def _token(key: ec.EllipticCurvePrivateKey = SIGNING_KEY, **overrides: object) -> str:
    claims = {
        "sub": "member-123",
        "aud": "authenticated",
        "iss": f"{PROJECT}/auth/v1",
        "exp": int(time.time()) + 3600,
        "role": "authenticated",
        "is_anonymous": True,
        **overrides,
    }
    return jwt.encode(claims, key, algorithm="ES256", headers={"kid": "test"})


@pytest.fixture
def verifier() -> TokenVerifier:
    return TokenVerifier(SETTINGS, jwks=_FakeJwks(SIGNING_KEY.public_key()))


def test_valid_anonymous_token_identifies_the_member(verifier: TokenVerifier) -> None:
    token = _token()
    member = verifier.member(token)
    assert member.id == "member-123"
    assert member.access_token == token


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(_token(exp=int(time.time()) - 120), id="expired"),
        pytest.param(_token(aud="anon"), id="wrong audience"),
        pytest.param(_token(iss="https://other.supabase.co/auth/v1"), id="other project"),
        pytest.param(_token(key=ec.generate_private_key(ec.SECP256R1())), id="forged"),
        pytest.param("not-a-jwt", id="garbage"),
    ],
)
def test_bad_tokens_are_rejected(verifier: TokenVerifier, token: str) -> None:
    with pytest.raises(HTTPException) as caught:
        verifier.member(token)
    assert caught.value.status_code == 401
    assert caught.value.detail == SIGN_IN_DETAIL


def test_signing_key_outage_is_temporary(verifier: TokenVerifier) -> None:
    class _Down:
        def get_signing_key_from_jwt(self, _token: str) -> None:
            raise jwt.PyJWKClientConnectionError("unreachable")

    with pytest.raises(HTTPException) as caught:
        TokenVerifier(SETTINGS, jwks=_Down()).member(_token())
    assert caught.value.status_code == 503


def test_supabase_mode_requires_sign_in_but_health_stays_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUPABASE_URL", PROJECT)
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        health = client.get("/api/health").json()
        resp = client.get("/api/plan")

    assert health["supabase_enabled"] is True
    assert health["supabase_url"] == PROJECT
    assert health["supabase_publishable_key"] == "sb_publishable_test"
    assert health["storage"] == "supabase"
    assert resp.status_code == 401
    assert resp.json()["detail"] == SIGN_IN_DETAIL
    assert resp.headers["www-authenticate"] == "Bearer"
