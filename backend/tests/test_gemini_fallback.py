"""Live-mode failures must degrade to demo answers instead of breaking the demo."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app
from app.services import gemini as gemini_module
from app.services.gemini import GeminiService


class _FailingModels:
    def embed_content(self, **_: object) -> None:
        raise ConnectionError("network down")

    def generate_content(self, **_: object) -> None:
        raise ConnectionError("network down")


class _FailingClient:
    def __init__(self, **_: object) -> None:
        self.models = _FailingModels()


@pytest.fixture
def live_but_broken(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(gemini_module.genai, "Client", _FailingClient)
    get_settings.cache_clear()


def test_chat_answer_falls_back_when_generation_fails(live_but_broken: None) -> None:
    service = GeminiService(Settings())
    assert service.enabled

    result = service.generate_answer("Deductible?", "Deductible is $2,000.", "")

    assert result.live is False
    assert "Demo mode" in result.text


def test_eob_scan_falls_back_when_vision_fails(live_but_broken: None) -> None:
    service = GeminiService(Settings())

    result = service.analyze_eob(b"img", "image/png", "")

    assert result.live is False
    assert result.data["line_items"]


def test_startup_indexing_failure_switches_app_to_demo_mode(live_but_broken: None) -> None:
    with TestClient(create_app()) as client:
        health = client.get("/api/health").json()
        assert health["gemini_enabled"] is False
        assert health["indexed_chunks"] > 0

        chat = client.post("/api/chat", json={"message": "What is my deductible?"})
        assert chat.status_code == 200
        assert chat.json()["demo_mode"] is True
        assert chat.json()["sources"]
