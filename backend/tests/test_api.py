"""End-to-end API tests that run fully offline in demo mode."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.schemas import BenefitsSnapshot
from app.services.benefits import estimate_out_of_pocket, extract_dollar_amount
from app.services.ingestion import chunk_text


def test_health_reports_demo_mode(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["vector_store"] == "in-memory"
    # Sample policy is auto-seeded on startup.
    assert body["indexed_chunks"] > 0


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


def test_document_ingest_increases_index(client: TestClient) -> None:
    before = client.get("/api/health").json()["indexed_chunks"]
    resp = client.post(
        "/api/documents",
        json={
            "title": "Dental Rider",
            "text": "Dental cleanings are covered twice per year at 100%. " * 50,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["chunks_indexed"] >= 1
    after = client.get("/api/health").json()["indexed_chunks"]
    assert after > before


def test_eob_scan_flags_overcharges(client: TestClient) -> None:
    files = {"file": ("bill.png", b"\x89PNG\r\n\x1a\nfake", "image/png")}
    resp = client.post("/api/eob/scan", files=files)
    assert resp.status_code == 200
    body = resp.json()
    assert body["demo_mode"] is True
    assert body["total_billed"] > 0
    assert len(body["line_items"]) > 0
    assert len(body["overcharge_flags"]) > 0
    # Sample bill: $45 preventive draw + $210 duplicate office visit.
    assert body["potential_savings"] == 255


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
