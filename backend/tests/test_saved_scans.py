"""Bill scans are remembered, count toward the deductible, and can be removed."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.routers.samples import SAMPLES_DIR
from app.services.gemini import EobResult
from app.services.storage import MAX_SAVED_SCANS

_SAMPLE_BILL = (SAMPLES_DIR / "sample-bill.pdf").read_bytes()
_PNG = b"\x89PNG\r\n\x1a\n"
# The sample plan: $2,000 deductible with $450 already met, 20% coinsurance.
_MET = 450
_DEDUCTIBLE = 2000


def _scan_sample(client: TestClient, name: str = "sample-bill.pdf") -> dict:
    resp = client.post("/api/eob/scan", files={"file": (name, _SAMPLE_BILL, "application/pdf")})
    assert resp.status_code == 200
    return resp.json()


def _bill(provider: str, *lines: tuple[float, float | None]) -> dict:
    return {
        "is_medical_bill": True,
        "provider": provider,
        "total_billed": sum(billed for billed, _ in lines),
        "line_items": [
            {
                "code": f"9921{i}",
                "description": "Office visit",
                "billed": billed,
                "covered": True,
                "flag": "",
                **({"plan_expected": expected} if expected is not None else {}),
            }
            for i, (billed, expected) in enumerate(lines)
        ],
        "overcharge_flags": [],
        "summary": f"A visit at {provider}.",
    }


@pytest.fixture
def live_bills(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> dict[bytes, dict]:
    """Pretend Gemini is live: each uploaded file's bytes map to the bill it contains."""
    replies: dict[bytes, dict] = {}
    monkeypatch.setattr(
        client.app.state.services.gemini,
        "analyze_eob",
        lambda **kw: EobResult(replies[kw["image_bytes"]], live=True),
    )
    return replies


def _scan(client: TestClient, bills: dict[bytes, dict], name: str, reply: dict) -> dict:
    data = _PNG + name.encode()
    bills[data] = reply
    resp = client.post("/api/eob/scan", files={"file": (f"{name}.png", data, "image/png")})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _benefits(client: TestClient) -> dict:
    return client.get("/api/plan").json()["benefits"]


def test_scan_is_saved_with_id_file_name_time_and_plan(client: TestClient) -> None:
    scan = _scan_sample(client, "march-bill.pdf")

    assert scan["scan_id"]
    assert scan["file_name"] == "march-bill.pdf"
    assert scan["scanned_at"]
    assert scan["file_sha256"]
    assert scan["plan_name"] == client.get("/api/plan").json()["plan_name"]
    assert client.get("/api/eob/scans").json() == [scan]
    assert client.get(f"/api/eob/scans/{scan['scan_id']}").json() == scan


def test_earlier_bills_are_kept_newest_first(client: TestClient, live_bills: dict) -> None:
    first = _scan(client, live_bills, "january", _bill("Clinic A", (100, 20)))
    second = _scan(client, live_bills, "february", _bill("Clinic B", (200, 40)))

    saved = client.get("/api/eob/scans").json()

    assert [s["scan_id"] for s in saved] == [second["scan_id"], first["scan_id"]]
    assert client.get(f"/api/eob/scans/{first['scan_id']}").json() == first


def test_listing_is_capped_but_every_bill_counts(client: TestClient, live_bills: dict) -> None:
    ids = [
        _scan(client, live_bills, f"bill-{i}", _bill(f"Clinic {i}", (100, 100)))["scan_id"]
        for i in range(MAX_SAVED_SCANS + 2)
    ]

    saved = [s["scan_id"] for s in client.get("/api/eob/scans").json()]

    assert saved == list(reversed(ids))[:MAX_SAVED_SCANS]
    assert _benefits(client)["deductible_met"] == _MET + 100 * (MAX_SAVED_SCANS + 2)


def test_rescanning_the_same_file_replaces_it(client: TestClient) -> None:
    first = _scan_sample(client, "bill.pdf")
    again = _scan_sample(client, "bill-again.pdf")

    saved = client.get("/api/eob/scans").json()

    assert [s["scan_id"] for s in saved] == [again["scan_id"]]
    assert client.get(f"/api/eob/scans/{first['scan_id']}").status_code == 404


def test_rescanning_does_not_count_a_bill_twice(client: TestClient, live_bills: dict) -> None:
    reply = _bill("Clinic", (300, 300))
    _scan(client, live_bills, "same", reply)
    again = _scan(client, live_bills, "same", reply)

    assert again["applied_to_deductible"] == 300
    assert _benefits(client)["deductible_met"] == _MET + 300


def test_bill_total_uses_what_the_member_should_pay(client: TestClient, live_bills: dict) -> None:
    scan = _scan(client, live_bills, "visit", _bill("Clinic", (250, 25), (100, 0)))

    assert scan["total_billed"] == 350
    assert scan["you_owe"] == 25
    assert scan["applied_to_deductible"] == 25


def test_lines_without_an_expected_cost_are_estimated_from_the_plan(
    client: TestClient, live_bills: dict
) -> None:
    # $1,550 of deductible is left, so a $1,000 charge is paid in full by the member.
    first = _scan(client, live_bills, "mri", _bill("Imaging", (1000, None)))
    # Now $550 is left: $550 + 20% of the other $450 = $640.
    second = _scan(client, live_bills, "follow-up", _bill("Imaging", (1000, None)))

    assert first["you_owe"] == 1000
    assert second["you_owe"] == 640
    assert second["applied_to_deductible"] == 550


def test_bills_fill_the_deductible_up_to_the_limit(client: TestClient, live_bills: dict) -> None:
    first = _scan(client, live_bills, "er", _bill("Hospital", (400, 400)))
    assert first["applied_to_deductible"] == 400
    assert _benefits(client)["deductible_met"] == _MET + 400

    second = _scan(client, live_bills, "surgery", _bill("Hospital", (5000, 3000)))

    assert second["you_owe"] == 3000
    assert second["applied_to_deductible"] == _DEDUCTIBLE - _MET - 400
    benefits = _benefits(client)
    assert benefits["deductible_met"] == _DEDUCTIBLE
    assert benefits["deductible_remaining"] == 0


def _fill_then_coinsurance(client: TestClient, bills: dict) -> tuple[dict, dict]:
    # $1,550 of deductible is left: $1,550 + 20% of the other $50 = $1,560.
    big = _scan(client, bills, "surgery", _bill("Hospital", (1600, None)))
    # The deductible is met, so the member only owes 20% coinsurance.
    follow_up = _scan(client, bills, "follow-up", _bill("Hospital", (1000, None)))
    assert (big["you_owe"], big["applied_to_deductible"]) == (1560, 1550)
    assert (follow_up["you_owe"], follow_up["applied_to_deductible"]) == (200, 0)
    return big, follow_up


def test_coinsurance_never_counts_toward_the_deductible(
    client: TestClient, live_bills: dict
) -> None:
    big, _ = _fill_then_coinsurance(client, live_bills)

    client.delete(f"/api/eob/scans/{big['scan_id']}")

    assert _benefits(client)["deductible_met"] == _MET


def test_rescan_is_not_discounted_by_another_bills_coinsurance(
    client: TestClient, live_bills: dict
) -> None:
    _fill_then_coinsurance(client, live_bills)

    again = _scan(client, live_bills, "surgery", _bill("Hospital", (1600, None)))

    assert (again["you_owe"], again["applied_to_deductible"]) == (1560, 1550)
    assert _benefits(client)["deductible_met"] == _DEDUCTIBLE


def test_scanner_is_told_the_deductible_left_before_the_bill(
    client: TestClient, live_bills: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    _scan(client, live_bills, "er", _bill("Hospital", (400, 400)))
    gemini = client.app.state.services.gemini
    scan_eob = gemini.analyze_eob
    seen: list[str] = []

    def recording(**kw: object) -> EobResult:
        seen.append(str(kw["benefits"]))
        return scan_eob(**kw)

    monkeypatch.setattr(gemini, "analyze_eob", recording)
    _scan(client, live_bills, "follow-up", _bill("Hospital", (100, 100)))
    _scan(client, live_bills, "er", _bill("Hospital", (400, 400)))

    assert "$850.00 of $2,000.00 met ($1,150.00 remaining)" in seen[0]
    # A rescan is judged as if the earlier copy of the same file weren't there.
    assert "$550.00 of $2,000.00 met ($1,450.00 remaining)" in seen[1]


def test_fully_covered_bill_leaves_the_deductible_alone(client: TestClient) -> None:
    scan = _scan_sample(client)

    assert scan["you_owe"] == 0
    assert scan["applied_to_deductible"] == 0
    assert _benefits(client)["deductible_met"] == _MET


def test_chat_uses_the_deductible_after_bills(client: TestClient, live_bills: dict) -> None:
    _scan(client, live_bills, "visit", _bill("Clinic", (500, 500)))

    body = client.post("/api/chat", json={"message": "What is my deductible?"}).json()

    assert body["benefits"]["deductible_met"] == _MET + 500


def test_removing_a_bill_stops_it_counting(client: TestClient, live_bills: dict) -> None:
    keep = _scan(client, live_bills, "keep", _bill("Clinic A", (100, 100)))
    drop = _scan(client, live_bills, "drop", _bill("Clinic B", (300, 300)))

    assert client.delete(f"/api/eob/scans/{drop['scan_id']}").status_code == 204

    assert [s["scan_id"] for s in client.get("/api/eob/scans").json()] == [keep["scan_id"]]
    assert _benefits(client)["deductible_met"] == _MET + 100
    assert client.delete(f"/api/eob/scans/{drop['scan_id']}").status_code == 404


def test_unknown_scan_is_404(client: TestClient) -> None:
    assert client.get("/api/eob/scans/nope").status_code == 404
    assert client.delete("/api/eob/scans/nope").status_code == 404


def test_failed_scan_is_not_saved(client: TestClient) -> None:
    photo = _PNG + b"not the sample"
    resp = client.post("/api/eob/scan", files={"file": ("x.png", photo, "image/png")})

    assert resp.status_code == 503
    assert client.get("/api/eob/scans").json() == []


def test_changing_plans_forgets_scans_and_their_deductible(
    client: TestClient, live_bills: dict
) -> None:
    _scan(client, live_bills, "visit", _bill("Clinic", (500, 500)))
    client.post("/api/plan/sample")
    assert client.get("/api/eob/scans").json() == []
    assert _benefits(client)["deductible_met"] == _MET

    _scan(client, live_bills, "visit-2", _bill("Clinic", (500, 500)))
    client.post("/api/plan/clear")
    assert client.get("/api/eob/scans").json() == []


def test_scans_can_be_cleared(client: TestClient, live_bills: dict) -> None:
    _scan(client, live_bills, "visit", _bill("Clinic", (500, 500)))

    assert client.delete("/api/eob/scans").status_code == 204
    assert client.get("/api/eob/scans").json() == []
    assert _benefits(client)["deductible_met"] == _MET
