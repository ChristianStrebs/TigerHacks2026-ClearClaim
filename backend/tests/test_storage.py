"""Per-member storage: in memory and through the Supabase Data API."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth import Member
from app.config import Settings
from app.main import STORAGE_DOWN_DETAIL
from app.schemas import BenefitsSnapshot, ChatResponse, EobScanResponse
from app.services import storage as storage_module
from app.services.benefits import sample_plan
from app.services.storage import (
    Chunk,
    InMemoryMemberStore,
    InMemoryStorage,
    PlanReplacedError,
    StorageError,
    SupabaseStorage,
)

ALICE = Member(id="alice", access_token="alice-token")
BOB = Member(id="bob", access_token="bob-token")
PLAN = sample_plan(Settings())


def _scan() -> EobScanResponse:
    return EobScanResponse(
        scan_id="0b6f7c2e-8f9a-4c55-9d7e-2a1b3c4d5e6f",
        file_name="bill.pdf",
        scanned_at=datetime.now(UTC),
        plan_name=PLAN.name,
        total_billed=565,
        line_items=[],
        overcharge_flags=[],
        summary="",
        demo_mode=False,
    )


def _answer() -> ChatResponse:
    return ChatResponse(
        answer="Hello",
        sources=[],
        benefits=BenefitsSnapshot(
            deductible_total=1,
            deductible_met=0,
            deductible_remaining=1,
            coinsurance_rate=0.2,
            oop_max=1,
        ),
        demo_mode=True,
    )


def test_members_never_see_each_others_data() -> None:
    storage = InMemoryStorage()
    alice = storage.for_member(ALICE)
    saved = alice.replace_plan(PLAN, [Chunk("Plan", "Coverage", [1.0, 0.0])], "offline:2")
    alice.add_scan(saved.id, _scan())
    alice.add_chat(saved.id, "Hi", _answer())

    bob = storage.for_member(BOB)
    assert bob.get_plan() is None
    assert bob.search([1.0, 0.0]) == []
    assert bob.list_scans() == []
    assert bob.list_chat() == []
    assert storage.for_member(ALICE).get_plan() == saved


def test_failed_replacement_keeps_the_old_plan_searchable() -> None:
    store = InMemoryStorage().for_member(ALICE)
    old = store.replace_plan(PLAN, [Chunk("Old plan", "Old coverage", [1.0, 0.0])], "offline:2")
    with pytest.raises(ValueError):
        store.replace_plan(PLAN, [Chunk("new", "a", [1.0, 0.0]), Chunk("new", "b", [1.0])], "x")
    assert store.get_plan() == old
    assert store.search([1.0, 0.0])[0].document == "Old plan"


def test_new_plan_drops_old_scans_and_chats_and_rejects_late_results() -> None:
    store = InMemoryStorage().for_member(ALICE)
    old = store.replace_plan(PLAN, [Chunk("Plan", "Coverage", [1.0])], "offline:1")
    store.add_scan(old.id, _scan())
    store.add_chat(old.id, "Hi", _answer())

    store.replace_plan(PLAN, [Chunk("Plan", "Coverage", [1.0])], "offline:1")
    assert store.list_scans() == []
    assert store.list_chat() == []
    with pytest.raises(PlanReplacedError):
        store.add_scan(old.id, _scan())


# --------------------------------------------------------------------------- #
# Supabase, against a fake Data API
# --------------------------------------------------------------------------- #
SUPABASE = Settings(
    SUPABASE_URL="https://example.supabase.co", SUPABASE_PUBLISHABLE_KEY="sb_publishable_test"
)


def _supabase(handler) -> tuple[SupabaseStorage, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    return SupabaseStorage(SUPABASE, transport=httpx.MockTransport(record)), requests


def test_supabase_requests_carry_the_members_token_not_a_service_key() -> None:
    storage, requests = _supabase(lambda _: httpx.Response(200, json="plan-1"))
    saved = storage.for_member(ALICE).replace_plan(
        PLAN, [Chunk("Plan", "Coverage", [0.5])], "offline:1"
    )

    assert saved.id == "plan-1"
    [request] = requests
    assert request.url.path == "/rest/v1/rpc/replace_plan"
    assert request.headers["apikey"] == "sb_publishable_test"
    assert request.headers["authorization"] == "Bearer alice-token"
    body = json.loads(request.content)
    assert body["new_plan"]["name"] == PLAN.name
    assert body["new_chunks"] == [{"document": "Plan", "content": "Coverage", "embedding": [0.5]}]


def test_supabase_outage_is_not_followed_by_a_destructive_fallback() -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable", request=request)

    storage, requests = _supabase(unreachable)
    with pytest.raises(StorageError):
        storage.for_member(ALICE).replace_plan(PLAN, [Chunk("Plan", "Coverage", [1.0])], "x")
    assert [r.url.path for r in requests] == ["/rest/v1/rpc/replace_plan"]


def test_supabase_scan_for_a_replaced_plan_is_reported() -> None:
    storage, _ = _supabase(
        lambda _: httpx.Response(409, json={"code": "23503", "message": "foreign key"})
    )
    with pytest.raises(PlanReplacedError):
        storage.for_member(ALICE).add_scan("old-plan", _scan())


ISSUED_IN_FUTURE = {"code": "PGRST303", "message": "JWT issued at future"}


@pytest.fixture
def no_clock_skew_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(storage_module, "_CLOCK_SKEW_WAIT_SECONDS", 0)


@pytest.mark.usefixtures("no_clock_skew_wait")
def test_supabase_retries_a_token_signed_a_moment_ahead_of_its_clock() -> None:
    replies = iter([httpx.Response(401, json=ISSUED_IN_FUTURE), httpx.Response(200, json=[])])
    storage, requests = _supabase(lambda _: next(replies))
    assert storage.for_member(ALICE).list_scans() == []
    assert len(requests) == 2


@pytest.mark.usefixtures("no_clock_skew_wait")
def test_supabase_gives_up_when_the_token_stays_in_the_future() -> None:
    storage, requests = _supabase(lambda _: httpx.Response(401, json=ISSUED_IN_FUTURE))
    with pytest.raises(StorageError):
        storage.for_member(ALICE).list_scans()
    assert len(requests) == 3


def test_supabase_does_not_retry_other_rejections() -> None:
    storage, requests = _supabase(
        lambda _: httpx.Response(401, json={"code": "PGRST301", "message": "JWT expired"})
    )
    with pytest.raises(StorageError):
        storage.for_member(ALICE).list_scans()
    assert len(requests) == 1


def test_supabase_plan_row_round_trips() -> None:
    row = {
        "id": "plan-1",
        "name": PLAN.name,
        "source": "demo",
        "deductible_total": 2000,
        "deductible_met": 450,
        "coinsurance_rate": 0.2,
        "oop_max": 6000,
        "demo_fields": ["oop_max"],
        "summary": "Sample",
        "summary_live": False,
        "embed_model": "offline:768",
    }
    storage, requests = _supabase(lambda _: httpx.Response(200, json=[row]))
    saved = storage.for_member(ALICE).get_plan()
    assert saved is not None
    assert saved.id == "plan-1"
    assert saved.profile.deductible_met == 450.0
    assert saved.profile.demo_fields == ["oop_max"]
    assert saved.embed_model == "offline:768"
    assert requests[0].url.params["limit"] == "1"


def test_supabase_skips_lookups_for_malformed_scan_ids() -> None:
    storage, requests = _supabase(lambda _: httpx.Response(200, json=[]))
    assert storage.for_member(ALICE).get_scan("not-a-uuid") is None
    assert requests == []


def test_supabase_bill_ledger_reads_only_the_totals() -> None:
    rows = [
        {"id": "a", "you_owe": 125.5, "file_sha256": "abc"},
        {"id": "b", "you_owe": None, "file_sha256": None},
    ]
    storage, requests = _supabase(lambda _: httpx.Response(200, json=rows))

    ledger = storage.for_member(ALICE).bill_ledger()

    assert [(e.scan_id, e.file_sha256, e.you_owe) for e in ledger] == [
        ("a", "abc", 125.5),
        ("b", None, 0.0),
    ]
    select = requests[0].url.params["select"]
    assert "result->you_owe" in select
    assert "limit" not in requests[0].url.params


def test_supabase_deletes_one_scan_by_id() -> None:
    storage, requests = _supabase(lambda _: httpx.Response(204))
    store = storage.for_member(ALICE)

    store.delete_scan("not-a-uuid")
    store.delete_scan(_scan().scan_id)

    [request] = requests
    assert request.method == "DELETE"
    assert request.url.params["id"] == f"eq.{_scan().scan_id}"


def test_in_memory_ledger_keeps_bills_past_the_listing_cap() -> None:
    store = InMemoryStorage().for_member(ALICE)
    saved = store.replace_plan(PLAN, [Chunk("Plan", "Coverage", [1.0])], "offline:1")
    for i in range(8):
        store.add_scan(saved.id, _scan().model_copy(update={"scan_id": str(i), "you_owe": 10}))

    assert len(store.list_scans()) == 5
    assert sum(e.you_owe for e in store.bill_ledger()) == 80
    store.delete_scan("3")
    assert [e.scan_id for e in store.bill_ledger()] == ["0", "1", "2", "4", "5", "6", "7"]


def test_supabase_storage_requires_a_signed_in_member() -> None:
    storage, _ = _supabase(lambda _: httpx.Response(200, json=[]))
    with pytest.raises(StorageError):
        storage.for_member(Member(id="local", access_token=None))


# --------------------------------------------------------------------------- #
# API behavior when storage fails
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "endpoint,payload",
    [
        ("/api/plan/text", {"title": "New", "text": "Deductible: $7,000."}),
        ("/api/plan/sample", None),
    ],
)
def test_storage_failure_keeps_the_current_plan(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, endpoint: str, payload: dict | None
) -> None:
    before = client.get("/api/plan").json()

    def fail(*_args, **_kwargs):
        raise StorageError("database unavailable")

    monkeypatch.setattr(InMemoryMemberStore, "replace_plan", fail)
    response = client.post(endpoint, json=payload)
    assert response.status_code == 503
    assert response.json()["detail"] == STORAGE_DOWN_DETAIL
    assert client.get("/api/plan").json() == before
