"""Regression coverage for the small backend fixes shipped with the phone UI."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from google.genai import types

from app.config import Settings
from app.services.benefits import (
    extract_plan_numbers_offline,
    plan_from_extraction,
    sample_plan,
)
from app.services.gemini import GeminiService, _PLAN_SCHEMA
from app.services.vector_store import (
    Chunk,
    InMemoryVectorStore,
    IndexReplacementError,
    SupabaseVectorStore,
)


@pytest.mark.parametrize("percent,expected", [(0, 0), (1, 0.01), (0.5, 0.005), (20, 0.2), (100, 1)])
def test_percent_field_has_unambiguous_units(percent: float, expected: float) -> None:
    plan = plan_from_extraction(
        Settings(),
        "Zero deductible plan",
        {"deductible": 0, "coinsurance_percent": percent, "oop_max": 0},
        True,
    )
    assert plan.deductible_total == 0
    assert plan.coinsurance_rate == expected
    assert plan.oop_max == 0
    assert plan.demo_fields == []


@pytest.mark.parametrize("value", [None, -1, float("nan"), float("inf"), True, "0"])
def test_invalid_or_missing_numbers_use_labeled_defaults(value: object) -> None:
    plan = plan_from_extraction(
        Settings(),
        "Missing fields",
        {"deductible": value, "coinsurance_percent": value, "oop_max": value},
        False,
    )
    assert set(plan.demo_fields) == {"deductible_total", "coinsurance_rate", "oop_max"}


@pytest.mark.parametrize("percent", [0, 1, 0.5, 100])
def test_offline_percentage_round_trip(client: TestClient, percent: float) -> None:
    text = (
        f"Individual deductible: $0. You pay {percent}% coinsurance. Out-of-pocket maximum: $5,000."
    )
    response = client.post("/api/plan/text", json={"title": "Zero plan", "text": text})
    assert response.status_code == 200
    body = response.json()
    assert body["benefits"]["coinsurance_rate"] == percent / 100
    assert body["benefits"]["deductible_total"] == 0
    assert body["benefits"]["demo_fields"] == []
    assert f"{percent:g}%" in body["summary"]
    assert "**Deductible:** $0" in body["summary"]
    estimate = client.post("/api/chat", json={"message": "What will $1,000 surgery cost?"}).json()
    assert estimate["cost_estimate"]["estimated_out_of_pocket"] == 1000 * percent / 100


def test_live_extraction_distinguishes_zero_from_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    service = GeminiService(Settings())
    monkeypatch.setattr(
        service,
        "_generate",
        lambda *_: (
            '{"deductible":0,"coinsurance_percent":1,"oop_max":null,"summary":[],"full_text":""}'
        ),
    )
    extraction = service.extract_plan(text="A plan")
    plan = plan_from_extraction(Settings(), "Plan", extraction.data, extraction.live)
    assert plan.deductible_total == 0
    assert plan.coinsurance_rate == 0.01
    assert plan.demo_fields == ["oop_max"]
    schema = types.Schema.model_validate(_PLAN_SCHEMA)
    assert all(
        schema.properties[key].nullable for key in ("deductible", "coinsurance_percent", "oop_max")
    )


def test_zero_values_are_in_offline_summary() -> None:
    extraction = extract_plan_numbers_offline(
        "Deductible: $0. Coinsurance: 0%. Out-of-pocket maximum: $0."
    )
    assert "$0" in extraction["summary"]
    assert "0%" in extraction["summary"]


def test_sample_summary_uses_configured_numbers() -> None:
    plan = sample_plan(
        Settings(DEMO_DEDUCTIBLE_TOTAL=3500, DEMO_COINSURANCE_RATE=0.125, DEMO_OOP_MAX=8000)
    )
    assert "$3,500.00" in plan.summary
    assert "12.5%" in plan.summary
    assert "87.5%" in plan.summary
    assert "$8,000.00" in plan.summary


def test_failed_memory_replacement_preserves_searchable_old_index() -> None:
    store = InMemoryVectorStore()
    store.add([Chunk("Old plan", "Old coverage", [1, 0])])
    with pytest.raises(ValueError):
        store.replace([Chunk("new", "a", [1, 0]), Chunk("new", "b", [1])])
    assert store.count() == 1
    assert store.search([1, 0])[0].document == "Old plan"
    store.replace([Chunk("New plan", "New coverage", [0, 1])])
    assert store.search([0, 1])[0].document == "New plan"


def test_supabase_replace_uses_only_atomic_rpc() -> None:
    calls = []

    def rpc(name, payload):
        calls.append((name, payload))
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=1))

    store = SupabaseVectorStore.__new__(SupabaseVectorStore)
    store._client = SimpleNamespace(rpc=rpc)  # No table()/delete()/upsert() fallback available.
    chunk = Chunk("Plan", "Coverage", [1, 0])
    assert store.replace([chunk]) == 1
    assert calls[0][0] == "replace_documents"
    assert calls[0][1]["new_documents"][0]["id"] == chunk.id


def test_supabase_error_is_not_followed_by_destructive_fallback() -> None:
    def rpc(*_):
        raise ConnectionError("unreachable")

    store = SupabaseVectorStore.__new__(SupabaseVectorStore)
    store._client = SimpleNamespace(rpc=rpc)
    with pytest.raises(IndexReplacementError, match="0002_atomic_document_replacement"):
        store.replace([Chunk("New", "Coverage", [1, 0])])


@pytest.mark.parametrize(
    "endpoint,payload",
    [
        ("/api/plan/text", {"title": "New", "text": "Deductible: $7,000."}),
        ("/api/plan/reset", None),
    ],
)
def test_index_failure_does_not_publish_new_plan(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, endpoint: str, payload: dict | None
) -> None:
    before = client.get("/api/plan").json()
    store = client.app.state.services.vector_store
    old_hits = store.search(client.app.state.services.gemini.embed_query("deductible"))

    def fail(_):
        raise IndexReplacementError("Index unavailable; previous state was not replaced.")

    monkeypatch.setattr(store, "replace", fail)
    response = client.post(endpoint, json=payload)
    assert response.status_code == 503
    assert "Index unavailable" in response.json()["detail"]
    assert client.get("/api/plan").json() == before
    assert store.search(client.app.state.services.gemini.embed_query("deductible")) == old_hits
