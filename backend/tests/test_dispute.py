"""The dispute kit: always available, and it names every flagged charge and protection."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.config import Settings
from app.schemas import EobLineItem, EobScanResponse
from app.services.dispute import NO_SURPRISES_HELP_DESK, dispute_kit, template_kit
from app.services.gemini import DisputeResult, GeminiService
from app.services.rights import check_rights


def _scan_sample(client: TestClient, name: str) -> dict:
    pdf = client.get(f"/api/samples/{name}").content
    scan = client.post("/api/eob/scan", files={"file": (name, pdf, "application/pdf")})
    scan.raise_for_status()
    return scan.json()


def _saved_scan(*items: EobLineItem, you_owe: float = 0.0) -> EobScanResponse:
    return EobScanResponse(
        scan_id="scan-1",
        file_name="bill.pdf",
        scanned_at=datetime.now(UTC),
        plan_name="Tiger Health Silver PPO",
        provider="Boone Imaging",
        total_billed=sum(item.billed for item in items),
        line_items=list(items),
        overcharge_flags=[],
        you_owe=you_owe,
        rights=check_rights(list(items)),
        summary="",
        demo_mode=False,
    )


class _Drafts:
    """Stands in for GeminiService.draft_dispute."""

    def __init__(self, result: DisputeResult) -> None:
        self.result = result

    def draft_dispute(self, bill: str, plan_excerpts: str) -> DisputeResult:
        return self.result


def test_unknown_scan_is_404(client: TestClient) -> None:
    assert client.post("/api/eob/scans/nope/dispute").status_code == 404


def test_needs_a_plan_first(client: TestClient) -> None:
    scan = _scan_sample(client, "surprise-bill.pdf")
    client.post("/api/plan/clear").raise_for_status()

    assert client.post(f"/api/eob/scans/{scan['scan_id']}/dispute").status_code == 409


def test_surprise_bill_kit_names_each_charge_and_the_protection(client: TestClient) -> None:
    scan = _scan_sample(client, "surprise-bill.pdf")

    response = client.post(f"/api/eob/scans/{scan['scan_id']}/dispute")

    assert response.status_code == 200
    kit = response.json()
    assert kit["demo_mode"] is True
    letter = kit["letter"]
    for text in ("01400", "$2,100.00", "64447", "$600.00", "$1,780.00", "$2,700.00"):
        assert text in letter
    finding = scan["rights"][0]
    assert finding["title"] in letter
    assert finding["citation_url"] in letter
    assert "[Your name]" in letter and "[Account number]" in letter
    assert any("01400" in line for line in kit["call_script"])
    assert "reference number" in kit["call_script"][-1]
    assert any(NO_SURPRISES_HELP_DESK in step for step in kit["checklist"])
    assert kit["deadline_note"]


def test_wellness_bill_kit_lists_every_flagged_line(client: TestClient) -> None:
    scan = _scan_sample(client, "sample-bill.pdf")

    kit = client.post(f"/api/eob/scans/{scan['scan_id']}/dispute").json()

    for item in scan["line_items"]:
        assert item["flag"] in kit["letter"]
    for finding in scan["rights"]:
        assert finding["title"] in kit["letter"]
    assert not any(NO_SURPRISES_HELP_DESK in step for step in kit["checklist"])


def test_bill_without_problems_asks_for_a_check_not_a_correction() -> None:
    scan = _saved_scan(
        EobLineItem(
            code="70553", description="MRI brain", billed=900, plan_expected=900, covered=True
        ),
        you_owe=900,
    )

    kit = template_kit(scan)

    assert "look wrong" not in kit.letter
    assert "patient protections" not in kit.letter
    assert "expect to owe" not in kit.letter
    assert "go over the charges" in kit.call_script[1]


def test_denied_charge_gets_the_appeal_deadline() -> None:
    scan = _saved_scan(
        EobLineItem(
            code="70553", description="MRI brain", billed=900, covered=False, flag="Denied."
        )
    )

    kit = template_kit(scan)

    assert any("180 days" in step for step in kit.checklist)
    assert "180 days" in kit.deadline_note


def test_uses_geminis_draft_when_complete() -> None:
    draft = {
        "letter": "Dear billing office, [Your name]",
        "call_script": ["Hi, I'm calling about my bill."],
        "checklist": ["Send the letter."],
        "deadline_note": "Act soon.",
    }
    scan = _saved_scan(EobLineItem(code="1", description="Visit", billed=100, covered=True))

    kit = dispute_kit(_Drafts(DisputeResult(draft, live=True)), scan, "")

    assert kit.demo_mode is False
    assert kit.letter == draft["letter"]


def test_falls_back_to_the_template_when_geminis_draft_is_incomplete() -> None:
    scan = _saved_scan(EobLineItem(code="1", description="Visit", billed=100, covered=True))
    incomplete = DisputeResult({"letter": "Hi", "call_script": []}, live=True)
    empty = DisputeResult(
        {"letter": " ", "call_script": ["Hi"], "checklist": ["Send"], "deadline_note": ""},
        live=True,
    )

    for result in (incomplete, empty, DisputeResult({}, live=False)):
        kit = dispute_kit(_Drafts(result), scan, "")
        assert kit.demo_mode is True
        assert "[Your name]" in kit.letter


def test_invalid_gemini_json_is_not_live() -> None:
    service = GeminiService(Settings())
    service._client = SimpleNamespace(
        models=SimpleNamespace(generate_content=lambda **_: SimpleNamespace(text="not json"))
    )

    assert service.draft_dispute("bill", "") == DisputeResult({}, live=False)
