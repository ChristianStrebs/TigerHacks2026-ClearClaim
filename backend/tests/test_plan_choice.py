"""Visitors choose sample data or their own plan; nothing fake loads on its own."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.dependencies import NO_PLAN_DETAIL
from app.services.storage import MemberStore


def test_new_visitor_has_no_plan_or_sample_data(
    fresh_client: TestClient, local_store: MemberStore
) -> None:
    plan = fresh_client.get("/api/plan").json()

    assert plan == {
        "plan_name": None,
        "source": "none",
        "benefits": None,
        "summary": "",
        "demo_mode": False,
    }
    assert local_store.chunk_count() == 0


def test_chat_asks_visitor_to_choose_a_plan_first(fresh_client: TestClient) -> None:
    resp = fresh_client.post("/api/chat", json={"message": "What is my deductible?"})

    assert resp.status_code == 409
    assert resp.json()["detail"] == NO_PLAN_DETAIL


def test_bill_scan_asks_visitor_to_choose_a_plan_first(fresh_client: TestClient) -> None:
    files = {"file": ("bill.png", b"\x89PNG\r\n\x1a\nfake", "image/png")}

    resp = fresh_client.post("/api/eob/scan", files=files)

    assert resp.status_code == 409
    assert resp.json()["detail"] == NO_PLAN_DETAIL


def test_choosing_sample_data_loads_the_sample_plan(
    fresh_client: TestClient, local_store: MemberStore
) -> None:
    body = fresh_client.post("/api/plan/sample").json()

    assert body["source"] == "demo"
    assert body["benefits"]["deductible_total"] == 2000
    assert local_store.chunk_count() > 0
    assert fresh_client.post("/api/chat", json={"message": "Deductible?"}).status_code == 200


def test_reset_is_kept_as_an_alias_for_the_sample_plan(fresh_client: TestClient) -> None:
    assert fresh_client.post("/api/plan/reset").json()["source"] == "demo"


def test_start_over_forgets_the_plan(client: TestClient, local_store: MemberStore) -> None:
    body = client.post("/api/plan/clear").json()

    assert body["source"] == "none"
    assert local_store.chunk_count() == 0
    assert client.post("/api/chat", json={"message": "Deductible?"}).status_code == 409
