"""Unusual input that should get a clear answer instead of a crash or a misleading error."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import TokenVerifier
from app.config import Settings
from app.routers.plan import UNREADABLE_PDF_DETAIL
from app.services.benefits import plan_from_extraction
from app.services.gemini import EobResult, GeminiService, PlanResult
from app.services.ingestion import chunk_text
from app.services.storage import MemberStore
from app.services.uploads import UNREADABLE_FILE_DETAIL
from tests.pdf_utils import make_text_pdf
from tests.test_auth import SETTINGS, SIGNING_KEY, _FakeJwks, _token

_BILL_LINE = {
    "code": "99213",
    "description": "Office visit",
    "billed": 180,
    "plan_expected": 25,
    "covered": True,
    "flag": None,
}


def _upload_bill(client: TestClient, content: bytes = b"\x89PNG\r\n\x1a\nphoto"):
    return client.post("/api/eob/scan", files={"file": ("bill.png", content, "image/png")})


def test_overlong_question_is_rejected_before_asking_the_ai(client: TestClient) -> None:
    resp = client.post("/api/chat", json={"message": "x" * 4001})
    assert resp.status_code == 422


def test_blank_question_is_rejected(client: TestClient) -> None:
    resp = client.post("/api/chat", json={"message": "   \n "})
    assert resp.status_code == 422


def test_overlong_pasted_plan_is_rejected(client: TestClient) -> None:
    text = "Individual deductible: $3,000. Out-of-pocket maximum: $7,500. " * 4_000
    resp = client.post("/api/plan/text", json={"title": "Huge", "text": text})
    assert resp.status_code == 422
    assert client.get("/api/plan").json()["source"] == "demo"


def test_blank_pasted_plan_is_rejected(client: TestClient) -> None:
    resp = client.post("/api/plan/text", json={"title": "Blank", "text": "  \n\t "})
    assert resp.status_code == 422


def test_text_without_spaces_still_fits_saved_chunks() -> None:
    chunks = chunk_text("deductible" + "a" * 50_000 + " coinsurance 20%")
    assert chunks
    assert max(len(chunk) for chunk in chunks) <= 4_000


def test_long_unbroken_paste_saves_a_plan(client: TestClient, local_store: MemberStore) -> None:
    text = "Individual deductible: $1,500. Out-of-pocket maximum: $5,000. " + "z" * 30_000
    resp = client.post("/api/plan/text", json={"title": "Odd paste", "text": text})
    assert resp.status_code == 200
    assert local_store.chunk_count() >= 1


def test_very_long_plan_name_is_shortened() -> None:
    plan = plan_from_extraction(Settings(), "fallback", {"plan_name": "Gold " * 200}, True)
    assert 0 < len(plan.name) <= 300


def _live_gemini(reply: str) -> tuple[GeminiService, list[object]]:
    """A Gemini service whose model returns ``reply`` and records what it was sent."""
    sent: list[object] = []

    def generate_content(*, contents: object, **_: object) -> SimpleNamespace:
        sent.append(contents)
        return SimpleNamespace(text=reply)

    service = GeminiService(Settings())
    service._client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    return service, sent


def test_scanned_pdf_with_only_page_numbers_is_read_as_an_image() -> None:
    service, sent = _live_gemini('{"is_benefits_document": true, "summary": []}')

    service.extract_plan(text="Page 1 of 2", file_bytes=b"%PDF-scan", mime_type="application/pdf")

    assert isinstance(sent[0], list), "the pages should be sent, not the stray page number"


def test_pasted_short_text_is_still_read_as_text() -> None:
    service, sent = _live_gemini('{"is_benefits_document": true, "summary": []}')

    service.extract_plan(text="Deductible $500. Coinsurance 10%.")

    assert isinstance(sent[0], str)


def test_scanned_plan_is_indexed_from_the_transcription(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    reading = {
        "is_benefits_document": True,
        "plan_name": "Scanned Gold",
        "deductible": 1000,
        "full_text": "Scanned Gold plan. Individual deductible is $1,000 per year.",
        "summary": "- Deductible: $1,000",
    }
    monkeypatch.setattr(
        client.app.state.services.gemini,
        "extract_plan",
        lambda **_: PlanResult(reading, live=True),
    )
    scan = make_text_pdf(["Page 1 of 2"])

    resp = client.post("/api/plan/upload", files={"file": ("scan.pdf", scan, "application/pdf")})

    assert resp.status_code == 200
    chat = client.post("/api/chat", json={"message": "What is my deductible?"}).json()
    assert "Scanned Gold plan" in chat["sources"][0]["snippet"]


@pytest.mark.parametrize("reply", ['[{"code": "99213"}]', '"just text"', "42"])
def test_ai_reply_that_is_not_an_object_counts_as_unreadable(reply: str) -> None:
    service, _ = _live_gemini(reply)

    assert service.analyze_eob(b"img", "image/png", "").live is False
    assert service.extract_plan(text="Deductible $500. " * 20).live is False


def test_long_documents_are_embedded_in_batches_the_api_accepts() -> None:
    batches: list[int] = []

    def embed_content(*, contents: list[str], **_: object) -> SimpleNamespace:
        batches.append(len(contents))
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.0]) for _ in contents])

    service = GeminiService(Settings())
    service._client = SimpleNamespace(models=SimpleNamespace(embed_content=embed_content))

    vectors = service.embed_texts([f"chunk {i}" for i in range(250)])

    assert len(vectors) == 250
    assert batches == [100, 100, 50]


@pytest.mark.parametrize("route", ["/api/plan/upload", "/api/eob/scan"])
@pytest.mark.parametrize(
    ("content", "mime"),
    [
        pytest.param(b"this is not really a pdf", "application/pdf", id="text named .pdf"),
        pytest.param(b"%PDF-1.4 hello", "image/png", id="pdf named .png"),
        pytest.param(b"\xff\xd8\xff\xe0 jpeg", "image/webp", id="jpeg named .webp"),
    ],
)
def test_file_that_is_not_what_it_claims_is_rejected_before_the_ai(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, route: str, content: bytes, mime: str
) -> None:
    gemini = client.app.state.services.gemini

    def never(**_: object) -> None:
        raise AssertionError("the AI should not see a damaged file")

    monkeypatch.setattr(gemini, "extract_plan", never)
    monkeypatch.setattr(gemini, "analyze_eob", never)

    resp = client.post(route, files={"file": ("upload", content, mime)})

    assert resp.status_code == 400
    assert resp.json()["detail"] == UNREADABLE_FILE_DETAIL


def test_damaged_pdf_gets_a_plain_message(client: TestClient) -> None:
    resp = client.post(
        "/api/plan/upload",
        files={"file": ("plan.pdf", b"%PDF-1.4 truncated", "application/pdf")},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == UNREADABLE_PDF_DETAIL


@pytest.mark.parametrize(
    "total",
    [
        pytest.param("$180.00", id="money string"),
        pytest.param(None, id="missing"),
        pytest.param("unknown", id="words"),
    ],
)
def test_odd_bill_total_does_not_crash(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, total: object
) -> None:
    reply = {"provider": "Clinic", "total_billed": total, "line_items": [_BILL_LINE]}
    monkeypatch.setattr(
        client.app.state.services.gemini, "analyze_eob", lambda **_: EobResult(reply, live=True)
    )

    resp = _upload_bill(client)

    assert resp.status_code == 200
    assert resp.json()["total_billed"] == 180


def test_odd_line_item_amounts_are_read(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    line = {**_BILL_LINE, "billed": "$1,180.50", "plan_expected": "$25"}
    reply = {"provider": "Clinic", "total_billed": 1180.5, "line_items": [line]}
    monkeypatch.setattr(
        client.app.state.services.gemini, "analyze_eob", lambda **_: EobResult(reply, live=True)
    )

    resp = _upload_bill(client)

    assert resp.status_code == 200
    item = resp.json()["line_items"][0]
    assert item["billed"] == 1180.5
    assert item["plan_expected"] == 25


def test_failed_scan_keeps_the_previous_saved_scan(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    gemini = client.app.state.services.gemini
    good = {"provider": "Clinic", "total_billed": 180, "line_items": [_BILL_LINE]}
    monkeypatch.setattr(gemini, "analyze_eob", lambda **_: EobResult(good, live=True))
    first = _upload_bill(client).json()

    junk = {"is_medical_bill": False, "line_items": []}
    monkeypatch.setattr(gemini, "analyze_eob", lambda **_: EobResult(junk, live=True))
    assert _upload_bill(client).status_code == 422

    assert client.get("/api/eob/scans").json()[0]["scan_id"] == first["scan_id"]


def test_token_issued_a_few_seconds_ahead_is_accepted() -> None:
    verifier = TokenVerifier(SETTINGS, jwks=_FakeJwks(SIGNING_KEY.public_key()))
    token = _token(iat=int(time.time()) + 5)
    assert verifier.member(token).id == "member-123"


def test_token_expired_long_ago_is_still_rejected() -> None:
    verifier = TokenVerifier(SETTINGS, jwks=_FakeJwks(SIGNING_KEY.public_key()))
    with pytest.raises(HTTPException) as caught:
        verifier.member(_token(exp=int(time.time()) - 600))
    assert caught.value.status_code == 401
