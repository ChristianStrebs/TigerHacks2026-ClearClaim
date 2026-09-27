"""Chat remembers earlier messages so follow-up questions make sense."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.schemas import ChatTurn
from app.services.gemini import GeminiService


class _RecordingModels:
    def __init__(self) -> None:
        self.contents: list = []

    def generate_content(self, *, contents: list, **_: object) -> SimpleNamespace:
        self.contents = contents
        return SimpleNamespace(text="It would cost less.")


def test_history_is_sent_to_gemini_as_ordered_turns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    get_settings.cache_clear()
    service = GeminiService(Settings())
    models = _RecordingModels()
    service._client = SimpleNamespace(models=models)
    history = [
        ChatTurn(role="user", text="How much is an $18,000 knee surgery?"),
        ChatTurn(role="assistant", text="About $4,840."),
    ]

    result = service.generate_answer("What about a $5,000 one?", "", "", history=history)

    assert result.live is True
    assert [c.role for c in models.contents] == ["user", "model", "user"]
    assert models.contents[0].parts[0].text == history[0].text
    assert "What about a $5,000 one?" in models.contents[-1].parts[0].text


def test_only_recent_history_is_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    get_settings.cache_clear()
    service = GeminiService(Settings())
    models = _RecordingModels()
    service._client = SimpleNamespace(models=models)
    history = [ChatTurn(role="user", text=f"question {i}") for i in range(15)]

    service.generate_answer("latest", "", "", history=history)

    assert len(models.contents) == 11
    assert models.contents[0].parts[0].text == "question 5"


def test_follow_up_retrieval_includes_previous_question(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    gemini = client.app.state.services.gemini
    queries: list[str] = []
    original = gemini.embed_query

    def recording_embed(text: str) -> list[float]:
        queries.append(text)
        return original(text)

    monkeypatch.setattr(gemini, "embed_query", recording_embed)

    resp = client.post(
        "/api/chat",
        json={
            "message": "What about a $5,000 one?",
            "history": [
                {"role": "user", "text": "How much is an $18,000 knee surgery?"},
                {"role": "assistant", "text": "About $4,840."},
            ],
        },
    )

    assert resp.status_code == 200
    assert "knee surgery" in queries[-1]
    assert resp.json()["cost_estimate"]["billed_amount"] == 5000


def test_too_much_history_is_rejected(client: TestClient) -> None:
    history = [{"role": "user", "text": "hi"}] * 21

    resp = client.post("/api/chat", json={"message": "hello", "history": history})

    assert resp.status_code == 422
