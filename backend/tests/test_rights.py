"""Each patient protection fires on the bills it covers, and only those."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.routers.samples import SAMPLES_DIR
from app.schemas import EobLineItem, EobScanResponse
from app.services.bills import describe_scan
from app.services.gemini import EobResult
from app.services.rights import _rules, check_rights


def _line(**details: object) -> EobLineItem:
    base = {"code": "99213", "description": "Office visit", "billed": 200, "covered": True}
    return EobLineItem.model_validate({**base, **details})


def _rule_ids(*items: EobLineItem) -> list[str]:
    return [finding.rule_id for finding in check_rights(items)]


# One bill line per rule that should trigger it, and near misses that shouldn't.
FIRES = {
    "preventive_care": _line(preventive=True, network="in"),
    "nsa_emergency": _line(emergency=True, network="out"),
    "nsa_ancillary": _line(provider_type="anesthesiology", network="out", facility_in_network=True),
    "nsa_air_ambulance": _line(provider_type="air_ambulance", network="out"),
    "ground_ambulance": _line(provider_type="ground_ambulance", network="out"),
    "appeal_right": _line(covered=False),
}
MISSES = {
    "preventive_care": [
        _line(preventive=True, network="out"),
        _line(preventive=True, network="unknown"),
        _line(preventive=True, network="in", billed=0),
    ],
    "nsa_emergency": [
        _line(emergency=True, network="in", facility_in_network=True),
        _line(emergency=False, network="out"),
        _line(emergency=True, network="out", provider_type="ground_ambulance"),
    ],
    "nsa_ancillary": [
        _line(provider_type="anesthesiology", network="out", facility_in_network=False),
        _line(provider_type="anesthesiology", network="out", facility_in_network=None),
        _line(provider_type="anesthesiology", network="in", facility_in_network=True),
        _line(provider_type="surgeon", network="out", facility_in_network=True),
    ],
    "nsa_air_ambulance": [_line(provider_type="air_ambulance", network="in")],
    "ground_ambulance": [_line(provider_type="ground_ambulance", network="unknown")],
    "appeal_right": [_line(covered=True), _line(covered=False, billed=0)],
}


@pytest.mark.parametrize("rule_id", FIRES)
def test_rule_fires_on_the_charge_it_protects(rule_id: str) -> None:
    assert _rule_ids(FIRES[rule_id]) == [rule_id]


@pytest.mark.parametrize(
    "rule_id,item", [(rule_id, item) for rule_id, items in MISSES.items() for item in items]
)
def test_rule_stays_quiet_on_a_near_miss(rule_id: str, item: EobLineItem) -> None:
    assert rule_id not in _rule_ids(item)


def test_every_rule_in_the_data_file_has_a_check() -> None:
    assert set(_rules()) == set(FIRES) | {"duplicate_charge"}


def test_a_plain_in_network_visit_has_no_findings() -> None:
    assert check_rights([_line(network="in")]) == []


def test_repeated_charge_is_a_duplicate() -> None:
    first = _line(code="99396", description="Preventive visit", billed=250)
    findings = check_rights([first, _line(network="in"), first])

    [duplicate] = findings
    assert duplicate.rule_id == "duplicate_charge"
    assert duplicate.lines == ["Preventive visit (99396)"]


def test_denied_repeat_of_a_charge_is_only_a_duplicate() -> None:
    visit = _line(network="in")
    assert _rule_ids(visit, visit.model_copy(update={"covered": False})) == ["duplicate_charge"]


def test_same_service_at_a_different_price_is_not_a_duplicate() -> None:
    assert _rule_ids(_line(billed=200), _line(billed=90)) == []


def test_lines_without_a_code_are_matched_by_description() -> None:
    lab = _line(code="", description="Blood test", billed=40)
    [finding] = check_rights([lab, lab])
    assert finding.lines == ["Blood test"]


def test_emergency_and_air_ambulance_do_not_double_count() -> None:
    flight = _line(provider_type="air_ambulance", network="out", emergency=True)
    assert _rule_ids(flight) == ["nsa_air_ambulance"]


def test_out_of_network_er_doctor_counts_once_as_emergency() -> None:
    er_doctor = _line(
        provider_type="emergency_medicine", network="out", facility_in_network=True, emergency=True
    )
    assert _rule_ids(er_doctor) == ["nsa_emergency"]


def test_findings_follow_the_rules_file_order_and_carry_its_wording() -> None:
    denied = FIRES["appeal_right"].model_copy(update={"code": "70450"})
    findings = check_rights([denied, FIRES["preventive_care"]])

    assert [f.rule_id for f in findings] == ["preventive_care", "appeal_right"]
    rule = _rules()["preventive_care"]
    assert findings[0].title == rule["title"]
    assert findings[0].citation_url == rule["citation_url"]
    assert findings[0].lines == ["Office visit (99213)"]


def test_older_saved_scans_load_without_rights() -> None:
    scan = EobScanResponse.model_validate(
        {
            "scan_id": "s",
            "file_name": "bill.pdf",
            "scanned_at": datetime.now(UTC),
            "plan_name": "Plan",
            "total_billed": 1,
            "line_items": [],
            "overcharge_flags": [],
            "summary": "",
            "demo_mode": False,
        }
    )
    assert scan.rights == []


def test_offline_sample_bill_shows_preventive_and_duplicate_rights(client: TestClient) -> None:
    pdf = (SAMPLES_DIR / "sample-bill.pdf").read_bytes()
    scan = client.post(
        "/api/eob/scan", files={"file": ("sample-bill.pdf", pdf, "application/pdf")}
    ).json()

    assert [finding["rule_id"] for finding in scan["rights"]] == [
        "preventive_care",
        "duplicate_charge",
    ]


def test_scan_saves_rights_and_the_chat_can_read_them(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    reply = {
        "is_medical_bill": True,
        "provider": "Valley Anesthesia Associates",
        "total_billed": 2400,
        "line_items": [
            {
                "code": "00142",
                "description": "Anesthesia",
                "billed": 2400,
                "plan_expected": 480,
                "covered": True,
                "flag": "",
                "network": "out",
                "facility_in_network": True,
                "emergency": False,
                "preventive": False,
                "provider_type": "anesthesiology",
            }
        ],
        "overcharge_flags": [],
        "summary": "Anesthesia during surgery.",
    }
    gemini = client.app.state.services.gemini
    monkeypatch.setattr(gemini, "analyze_eob", lambda **_: EobResult(reply, live=True))

    scan = client.post(
        "/api/eob/scan", files={"file": ("a.png", b"\x89PNG\r\n\x1a\nanes", "image/png")}
    ).json()
    saved = EobScanResponse.model_validate(client.get(f"/api/eob/scans/{scan['scan_id']}").json())

    [finding] = saved.rights
    assert finding.rule_id == "nsa_ancillary"
    assert finding.lines == ["Anesthesia (00142)"]
    text = describe_scan(saved)
    assert "Patient protections that may apply" in text
    assert finding.title in text
    assert finding.citation_url in text
