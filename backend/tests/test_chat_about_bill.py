"""After a bill scan, the chat can answer questions about that bill."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.routers.samples import SAMPLES_DIR
from app.services.bills import mentions_bill

_SAMPLE_BILL = (SAMPLES_DIR / "sample-bill.pdf").read_bytes()


def _scan_sample(client: TestClient) -> dict:
    files = {"file": ("sample-bill.pdf", _SAMPLE_BILL, "application/pdf")}
    return client.post("/api/eob/scan", files=files).json()


def _record_prompts(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    prompts: list[str] = []

    def fake_generate(contents: list, _config: object) -> str:
        prompts.append(contents[-1].parts[0].text)
        return "Here is what to do."

    monkeypatch.setattr(client.app.state.services.gemini, "_generate", fake_generate)
    return prompts


def test_chat_without_a_scan_has_no_bill(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompts = _record_prompts(client, monkeypatch)

    body = client.post("/api/chat", json={"message": "What is my deductible?"}).json()

    assert body["bill_scan_id"] is None
    assert "Latest scanned bill" not in prompts[-1]


def test_chat_sees_the_latest_scanned_bill(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    scan = _scan_sample(client)
    prompts = _record_prompts(client, monkeypatch)

    body = client.post("/api/chat", json={"message": "Why was I charged twice?"}).json()

    assert body["bill_scan_id"] == scan["scan_id"]
    assert "Latest scanned bill" in prompts[-1]
    assert "99396" in prompts[-1]
    assert "$565.00" in prompts[-1]


def test_bill_question_with_a_dollar_amount_is_not_a_cost_estimate(client: TestClient) -> None:
    _scan_sample(client)

    body = client.post("/api/chat", json={"message": "Why was I charged $250 twice?"}).json()

    assert body["cost_estimate"] is None


def test_offline_bill_question_describes_the_scan(client: TestClient) -> None:
    _scan_sample(client)

    body = client.post("/api/chat", json={"message": "What's wrong with my bill?"}).json()

    assert body["demo_mode"] is True
    assert "latest bill" in body["answer"]
    assert "99396" in body["answer"]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Why was I charged twice?", True),
        ("Can I dispute this bill?", True),
        ("However, how much will I owe for a $5,000 surgery?", False),
        ("What is a deductible?", False),
    ],
)
def test_mentions_bill(text: str, expected: bool) -> None:
    assert mentions_bill(text) is expected
