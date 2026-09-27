"""Bill scans are remembered so the member can come back to them and ask about them."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.routers.samples import SAMPLES_DIR
from app.services.storage import MAX_SAVED_SCANS

_SAMPLE_BILL = (SAMPLES_DIR / "sample-bill.pdf").read_bytes()


def _scan_sample(client: TestClient, name: str = "sample-bill.pdf") -> dict:
    resp = client.post("/api/eob/scan", files={"file": (name, _SAMPLE_BILL, "application/pdf")})
    assert resp.status_code == 200
    return resp.json()


def test_scan_is_saved_with_id_file_name_time_and_plan(client: TestClient) -> None:
    scan = _scan_sample(client, "march-bill.pdf")

    assert scan["scan_id"]
    assert scan["file_name"] == "march-bill.pdf"
    assert scan["scanned_at"]
    assert scan["plan_name"] == client.get("/api/plan").json()["plan_name"]
    assert client.get("/api/eob/scans").json() == [scan]
    assert client.get(f"/api/eob/scans/{scan['scan_id']}").json() == scan


def test_saved_scans_are_newest_first_and_capped(client: TestClient) -> None:
    ids = [_scan_sample(client, f"bill-{i}.pdf")["scan_id"] for i in range(MAX_SAVED_SCANS + 2)]

    saved = [s["scan_id"] for s in client.get("/api/eob/scans").json()]

    assert saved == list(reversed(ids))[:MAX_SAVED_SCANS]


def test_unknown_scan_is_404(client: TestClient) -> None:
    assert client.get("/api/eob/scans/nope").status_code == 404


def test_failed_scan_is_not_saved(client: TestClient) -> None:
    photo = b"\x89PNG\r\n\x1a\nnot the sample"
    resp = client.post("/api/eob/scan", files={"file": ("x.png", photo, "image/png")})

    assert resp.status_code == 503
    assert client.get("/api/eob/scans").json() == []


def test_changing_plans_forgets_scans(client: TestClient) -> None:
    _scan_sample(client)
    client.post("/api/plan/sample")
    assert client.get("/api/eob/scans").json() == []

    _scan_sample(client)
    client.post("/api/plan/clear")
    assert client.get("/api/eob/scans").json() == []


def test_scans_can_be_cleared(client: TestClient) -> None:
    _scan_sample(client)

    assert client.delete("/api/eob/scans").status_code == 204
    assert client.get("/api/eob/scans").json() == []
