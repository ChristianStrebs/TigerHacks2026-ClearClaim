"""Sample files must download and work end to end with the endpoints they feed."""

from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient

from app.routers.samples import SAMPLES, SAMPLES_DIR, offline_bill_analysis


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


def test_surprise_bill_scans_to_a_no_surprises_act_protection(client: TestClient) -> None:
    pdf = client.get("/api/samples/surprise-bill.pdf").content

    scan = client.post(
        "/api/eob/scan", files={"file": ("surprise-bill.pdf", pdf, "application/pdf")}
    ).json()

    assert scan["demo_mode"] is True
    assert scan["total_billed"] == 2700
    # The sample plan's $1,550 remaining deductible, then 20% of the other $1,150.
    assert scan["you_owe"] == 1780
    assert scan["potential_savings"] == 920
    assert [finding["rule_id"] for finding in scan["rights"]] == ["nsa_ancillary"]
    assert scan["rights"][0]["lines"] == [
        "Anesthesia for knee joint surgery (01400)",
        "Femoral nerve block injection (64447)",
    ]


def test_each_sample_bill_has_its_own_saved_analysis() -> None:
    bills = [name for name, sample in SAMPLES.items() if sample.kind == "bill"]
    providers = set()
    for name in bills:
        digest = hashlib.sha256((SAMPLES_DIR / name).read_bytes()).hexdigest()
        analysis = offline_bill_analysis(digest)
        assert analysis is not None, name
        providers.add(analysis["provider"])
    assert len(providers) == len(bills)


def test_other_files_have_no_saved_analysis() -> None:
    assert offline_bill_analysis(hashlib.sha256(b"my own bill").hexdigest()) is None


def test_sample_benefits_upload_reads_plan_numbers(client: TestClient) -> None:
    pdf = client.get("/api/samples/sample-benefits.pdf").content

    plan = client.post(
        "/api/plan/upload", files={"file": ("sample-benefits.pdf", pdf, "application/pdf")}
    ).json()

    assert plan["benefits"]["deductible_total"] == 3000
    assert plan["benefits"]["coinsurance_rate"] == 0.3
    assert plan["benefits"]["oop_max"] == 7500
    assert plan["benefits"]["demo_fields"] == []
