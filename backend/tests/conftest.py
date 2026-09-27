"""Shared fixtures. Every test runs offline, even if a developer's .env has real keys."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.auth import LOCAL_MEMBER
from app.config import get_settings
from app.main import create_app
from app.services.storage import MemberStore


@pytest.fixture(autouse=True)
def offline_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def fresh_client() -> Iterator[TestClient]:
    """The app as a new visitor sees it: no plan chosen yet."""
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def client(fresh_client: TestClient) -> TestClient:
    """The app after the visitor chose "Try with sample data"."""
    fresh_client.post("/api/plan/sample").raise_for_status()
    return fresh_client


@pytest.fixture
def local_store(fresh_client: TestClient) -> MemberStore:
    """What the app has saved for the single local member (no Supabase in tests)."""
    return fresh_client.app.state.services.storage.for_member(LOCAL_MEMBER)
