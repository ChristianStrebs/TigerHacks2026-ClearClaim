"""End-to-end API tests that run fully offline in demo mode."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.routers.eob import (
    AI_DOWN_DETAIL,
    NO_CHARGES_DETAIL,
    NOT_A_BILL_DETAIL,
    _parse_line_items,
    potential_savings,
)
from app.routers.samples import SAMPLES_DIR
from app.schemas import BenefitsSnapshot
from app.services.benefits import estimate_out_of_pocket, extract_dollar_amount
from app.services.gemini import EobResult
from app.services.ingestion import chunk_text

SAMPLE_BILL = SAMPLES_DIR / "sample-bill.pdf"


def test_health_reports_demo_mode(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["gemini_enabled"] is False
    assert body["supabase_enabled"] is False
    assert body["storage"] == "in-memory"


def test_sample_plan_includes_benefits(client: TestClient) -> None:
    benefits = client.get("/api/plan").json()["benefits"]
    assert benefits["deductible_total"] == 2000
    assert benefits["deductible_met"] == 450
    assert benefits["deductible_remaining"] == 1550
    assert benefits["coinsurance_rate"] == 0.2
    assert benefits["oop_max"] == 6000


def test_chat_returns_answer_sources_and_benefits(client: TestClient) -> None:
    resp = client.post(
        "/api/chat",
        json={"message": "What is my deductible?", "billed_amount": 1000},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"]
    assert body["demo_mode"] is True
    assert len(body["sources"]) > 0
    assert body["benefits"]["deductible_total"] == 2000
    assert body["cost_estimate"] is not None
    assert body["cost_estimate"]["estimated_out_of_pocket"] > 0


_BILL_REPLY = {
    "is_medical_bill": True,
    "provider": "Clinic",
    "total_billed": 120,
    "line_items": [
        {"code": "99213", "description": "Office visit", "billed": 120,
         "plan_expected": 25, "covered": True, "flag": ""},
    ],
    "overcharge_flags": [],
    "summary": "A routine office visit.",
}


def _live_eob(monkeypatch: pytest.MonkeyPatch, client: TestClient, reply: dict) -> None:
    gemini = client.app.state.services.gemini
    monkeypatch.setattr(gemini, "analyze_eob", lambda **_: EobResult(reply, live=True))


def test_offline_sample_bill_flags_overcharges(client: TestClient) -> None:
    files = {"file": ("sample-bill.pdf", SAMPLE_BILL.read_bytes(), "application/pdf")}
    resp = client.post("/api/eob/scan", files=files)
    assert resp.status_code == 200
    body = resp.json()
    assert body["demo_mode"] is True
    assert body["total_billed"] > 0
    assert len(body["line_items"]) > 0
    assert len(body["overcharge_flags"]) > 0
    # Sample bill: wellness visit, flu shot, and a duplicate visit the plan should cover.
    assert body["potential_savings"] == 565


def test_offline_scan_of_own_bill_never_shows_sample_result(client: TestClient) -> None:
    files = {"file": ("bill.png", b"\x89PNG\r\n\x1a\nreal bill", "image/png")}

    resp = client.post("/api/eob/scan", files=files)

    assert resp.status_code == 503
    assert resp.json()["detail"] == AI_DOWN_DETAIL


def test_eob_scan_accepts_iphone_heic_photos(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _live_eob(monkeypatch, client, _BILL_REPLY)

    resp = client.post("/api/eob/scan", files={"file": ("bill.heic", b"heic", "image/heic")})

    assert resp.status_code == 200
    assert resp.json()["demo_mode"] is False


def test_file_that_is_not_a_bill_is_rejected(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _live_eob(monkeypatch, client, {**_BILL_REPLY, "is_medical_bill": False, "line_items": []})

    resp = client.post("/api/eob/scan", files={"file": ("recipe.png", b"img", "image/png")})

    assert resp.status_code == 422
    assert resp.json()["detail"] == NOT_A_BILL_DETAIL


def test_bill_with_no_readable_charges_is_rejected(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _live_eob(monkeypatch, client, {**_BILL_REPLY, "line_items": [], "total_billed": 0})

    resp = client.post("/api/eob/scan", files={"file": ("blurry.png", b"img", "image/png")})

    assert resp.status_code == 422
    assert resp.json()["detail"] == NO_CHARGES_DETAIL


def test_auto_flagged_lines_appear_in_review_list(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = client.app.state.services
    reply = {
        "total_billed": 290,
        "line_items": [
            {"code": "99396", "description": "Wellness visit", "billed": 250,
             "plan_expected": 0, "covered": True, "flag": ""},
            {"code": "99396", "description": "Wellness visit", "billed": 250,
             "plan_expected": 0, "covered": False, "flag": "Duplicate of line 1."},
        ],
        "overcharge_flags": ["Line 2 is a duplicate."],
        "summary": "",
    }
    monkeypatch.setattr(
        services.gemini, "analyze_eob", lambda **_: EobResult(reply, live=True)
    )

    body = client.post(
        "/api/eob/scan", files={"file": ("bill.png", b"img", "image/png")}
    ).json()

    assert len(body["overcharge_flags"]) == 2
    assert "Wellness visit (99396)" in body["overcharge_flags"][1]


def test_fully_covered_lines_are_flagged_as_money_at_risk() -> None:
    items = _parse_line_items(
        [
            {"code": "99395", "description": "Wellness", "billed": 200, "plan_expected": 0,
             "covered": True, "flag": ""},
            {"code": "80053", "description": "Labs", "billed": 100, "plan_expected": 20,
             "covered": True, "flag": ""},
        ]
    )

    assert items[0].flag
    assert not items[1].flag
    assert potential_savings(items) == 200


def test_eob_scan_rejects_non_image(client: TestClient) -> None:
    files = {"file": ("notes.txt", b"hello", "text/plain")}
    resp = client.post("/api/eob/scan", files=files)
    assert resp.status_code == 415


def test_eob_scan_rejects_empty_file(client: TestClient) -> None:
    files = {"file": ("bill.png", b"", "image/png")}
    resp = client.post("/api/eob/scan", files=files)
    assert resp.status_code == 400


def test_chat_rejects_negative_procedure_cost(client: TestClient) -> None:
    resp = client.post("/api/chat", json={"message": "Cost?", "billed_amount": -5})
    assert resp.status_code == 422


def test_chat_estimates_cost_from_amount_in_question(client: TestClient) -> None:
    resp = client.post(
        "/api/chat", json={"message": "How much will an $18,000 knee surgery cost me?"}
    )
    assert resp.status_code == 200
    estimate = resp.json()["cost_estimate"]
    assert estimate["billed_amount"] == 18000
    # $1,550 remaining deductible + 20% of the other $16,450.
    assert estimate["estimated_out_of_pocket"] == 4840


def test_extract_dollar_amount_formats() -> None:
    assert extract_dollar_amount("a $18,000 surgery") == 18000
    assert extract_dollar_amount("about $2.5k") == 2500
    assert extract_dollar_amount("$ 99.50 copay") == 99.5
    assert extract_dollar_amount("no money mentioned") is None


def test_chunking_overlaps() -> None:
    chunks = chunk_text("word " * 2000, chunk_size=900, overlap=150)
    assert len(chunks) >= 2


def test_cost_estimate_math() -> None:
    benefits = BenefitsSnapshot(
        deductible_total=2000,
        deductible_met=450,
        deductible_remaining=1550,
        coinsurance_rate=0.2,
        oop_max=6000,
    )
    est = estimate_out_of_pocket(2000, benefits)
    # $1550 to deductible + 20% of remaining $450 = $1550 + $90 = $1640
    assert est.applied_to_deductible == 1550
    assert est.coinsurance == 90
    assert est.estimated_out_of_pocket == 1640
