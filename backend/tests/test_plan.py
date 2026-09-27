"""Submitting benefits replaces the demo plan; missing numbers stay flagged as demo."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.services.benefits import plan_from_extraction
from tests.pdf_utils import make_text_pdf

_FULL_PLAN = [
    "Tiger Health Silver PPO - Summary of Benefits",
    "Individual deductible: $3,000 per year.",
    "After the deductible you pay 30% coinsurance for most services.",
    "Out-of-pocket maximum: $7,500 per year.",
    "Preventive care is covered at 100%.",
]


def _upload(client: TestClient, content: bytes, name: str, mime: str):
    return client.post("/api/plan/upload", files={"file": (name, content, mime)})


def test_sample_plan_is_flagged_as_demo(client: TestClient) -> None:
    body = client.get("/api/plan").json()
    assert body["source"] == "demo"
    assert body["benefits"]["deductible_total"] == 2000
    assert set(body["benefits"]["demo_fields"]) == {
        "deductible_total",
        "coinsurance_rate",
        "oop_max",
    }
    assert "Deductible" in body["summary"]


def test_uploaded_plan_numbers_replace_demo_numbers(client: TestClient) -> None:
    resp = _upload(client, make_text_pdf(_FULL_PLAN), "silver.pdf", "application/pdf")

    assert resp.status_code == 200
    benefits = resp.json()["benefits"]
    assert resp.json()["source"] == "document"
    assert benefits["deductible_total"] == 3000
    assert benefits["deductible_met"] == 0
    assert benefits["coinsurance_rate"] == 0.3
    assert benefits["oop_max"] == 7500
    assert benefits["demo_fields"] == []

    chat = client.post("/api/chat", json={"message": "What is my deductible?"}).json()
    assert chat["benefits"]["deductible_total"] == 3000
    assert all(source["document"] == "silver.pdf" for source in chat["sources"])


def test_missing_numbers_keep_demo_values_and_are_flagged(client: TestClient) -> None:
    lines = ["Bronze plan", "Individual deductible: $5,000 per year."]
    resp = _upload(client, make_text_pdf(lines), "bronze.pdf", "application/pdf")

    benefits = resp.json()["benefits"]
    assert benefits["deductible_total"] == 5000
    assert benefits["oop_max"] == 6000
    assert set(benefits["demo_fields"]) == {"coinsurance_rate", "oop_max"}


def test_unreadable_photo_offline_keeps_current_plan(client: TestClient) -> None:
    resp = _upload(client, b"\x89PNG\r\n\x1a\nfake", "card.png", "image/png")

    assert resp.status_code == 422
    assert client.get("/api/plan").json()["source"] == "demo"


def test_rejects_unsupported_file_type(client: TestClient) -> None:
    resp = _upload(client, b"hello", "notes.txt", "text/plain")
    assert resp.status_code == 415


def test_reset_restores_sample_plan(client: TestClient) -> None:
    _upload(client, make_text_pdf(_FULL_PLAN), "silver.pdf", "application/pdf")

    body = client.post("/api/plan/reset").json()

    assert body["source"] == "demo"
    assert body["benefits"]["deductible_total"] == 2000
    chat = client.post("/api/chat", json={"message": "What is my deductible?"}).json()
    assert chat["sources"][0]["document"] == body["plan_name"]


def test_pasted_policy_returns_offline_summary(client: TestClient) -> None:
    text = (
        "ACME Corp Health Plan. Individual deductible: $2,000 per year. "
        "After the deductible you pay 20% coinsurance. "
        "Out-of-pocket maximum: $6,000 per year. "
        "Preventive care is covered at 100% with no deductible. "
        "Watch out: knee surgery needs prior authorization or a $500 penalty. "
    ) * 3
    before = client.get("/api/health").json()["indexed_chunks"]

    resp = client.post("/api/plan/text", json={"title": "ACME paste", "text": text})

    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "document"
    assert body["summary"]
    assert "Deductible" in body["summary"] or "deductible" in body["summary"].lower()
    assert body["benefits"]["deductible_total"] == 2000
    after = client.get("/api/health").json()
    assert after["indexed_chunks"] >= 1
    assert after["benefits"]["deductible_total"] == 2000
    assert before > 0


def test_paste_without_numbers_is_honest_about_demo_values(client: TestClient) -> None:
    resp = client.post(
        "/api/plan/text",
        json={"title": "Mystery booklet", "text": "Employee handbook cover page. " * 20},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["plan_name"] == "Mystery booklet"
    assert "couldn't pick out the key numbers" in body["summary"]
    assert set(body["benefits"]["demo_fields"]) == {
        "deductible_total",
        "coinsurance_rate",
        "oop_max",
    }


def test_coinsurance_accepts_percentages_and_rejects_nonsense() -> None:
    settings = Settings()

    as_percent = plan_from_extraction(settings, "x", {"coinsurance_percent": 20}, True)
    sub_percent = plan_from_extraction(settings, "x", {"coinsurance_percent": 0.25}, True)
    nonsense = plan_from_extraction(settings, "x", {"coinsurance_percent": 250}, True)

    assert as_percent.coinsurance_rate == 0.2
    assert sub_percent.coinsurance_rate == 0.0025
    assert "coinsurance_rate" in nonsense.demo_fields
