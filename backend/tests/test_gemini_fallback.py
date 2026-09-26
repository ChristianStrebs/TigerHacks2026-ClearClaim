"""Live-mode failures must degrade gracefully instead of breaking the demo."""

from __future__ import annotations

from types import SimpleNamespace

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


class _OverloadedPrimaryModels:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def generate_content(self, *, model: str, **_: object) -> SimpleNamespace:
        self.calls.append(model)
        if model == "primary-model":
            raise ConnectionError("503 high demand")
        return SimpleNamespace(text="Answer from backup")


@pytest.fixture
def live_but_broken(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(gemini_module.genai, "Client", _FailingClient)
    get_settings.cache_clear()


def test_chat_answer_falls_back_when_all_models_fail(live_but_broken: None) -> None:
    service = GeminiService(Settings())
    assert service.enabled

    result = service.generate_answer("Deductible?", "Deductible is $2,000.", "")

    assert result.live is False
    assert "+ button" in result.text


def test_backup_model_answers_when_primary_is_overloaded(live_but_broken: None) -> None:
    settings = Settings(GEMINI_CHAT_MODEL="primary-model", GEMINI_FALLBACK_MODELS="backup-model")
    service = GeminiService(settings)
    models = _OverloadedPrimaryModels()
    service._client = SimpleNamespace(models=models)

    result = service.generate_answer("Deductible?", "", "")

    assert result == ("Answer from backup", True)
    assert models.calls == ["primary-model", "backup-model"]


def test_plan_summary_list_becomes_one_bullet_per_line(live_but_broken: None) -> None:
    service = GeminiService(Settings())
    reply = '{"deductible": 3000, "summary": ["- Deductible: $3,000", "Copay: $35"]}'
    service._client = SimpleNamespace(
        models=SimpleNamespace(generate_content=lambda **_: SimpleNamespace(text=reply))
    )

    result = service.extract_plan(text="Deductible $3,000")

    assert result.live is True
    assert result.data["summary"] == "- Deductible: $3,000\n- Copay: $35"


def test_offline_answer_defines_general_benefit_terms() -> None:
    service = GeminiService(Settings())

    result = service.generate_answer("What is coinsurance?", "", "")

    assert result.live is False
    assert "Coinsurance" in result.text


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
