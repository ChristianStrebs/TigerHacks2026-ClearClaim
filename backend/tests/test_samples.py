"""Sample files must download and work end to end with the endpoints they feed."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_lists_sample_files_with_download_urls(client: TestClient) -> None:
    samples = client.get("/api/samples").json()

    assert {s["kind"] for s in samples} == {"bill", "benefits"}
    for sample in samples:
        assert client.get(sample["url"]).status_code == 200


def test_unknown_sample_is_404(client: TestClient) -> None:
    assert client.get("/api/samples/..%2Fsample_policy.txt").status_code == 404
    assert client.get("/api/samples/nope.pdf").status_code == 404


def test_sample_bill_scans_to_money_at_risk(client: TestClient) -> None:
    pdf = client.get("/api/samples/sample-bill.pdf")
    assert pdf.headers["content-type"] == "application/pdf"

    scan = client.post(
        "/api/eob/scan", files={"file": ("sample-bill.pdf", pdf.content, "application/pdf")}
    )

    assert scan.status_code == 200
    assert scan.json()["potential_savings"] == 565


def test_sample_benefits_upload_reads_plan_numbers(client: TestClient) -> None:
    pdf = client.get("/api/samples/sample-benefits.pdf").content

    plan = client.post(
        "/api/plan/upload", files={"file": ("sample-benefits.pdf", pdf, "application/pdf")}
    ).json()

    assert plan["benefits"]["deductible_total"] == 3000
    assert plan["benefits"]["coinsurance_rate"] == 0.3
    assert plan["benefits"]["oop_max"] == 7500
    assert plan["benefits"]["demo_fields"] == []
