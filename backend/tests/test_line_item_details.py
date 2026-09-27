"""Bill lines carry the details patient-protection checks need, even from messy AI output."""

from __future__ import annotations

from typing import get_args

import pytest
from fastapi.testclient import TestClient

from app.routers.eob import _parse_line_items
from app.routers.samples import SAMPLES_DIR
from app.schemas import EobLineItem, Network, ProviderType
from app.services.gemini import _EOB_INSTRUCTION, _EOB_SCHEMA, EobResult

_BASE = {"code": "00142", "description": "Anesthesia", "billed": 2400, "covered": True}


def _line(**details: object) -> EobLineItem:
    return EobLineItem.model_validate({**_BASE, **details})


def test_details_default_to_unknown_for_older_saved_scans() -> None:
    line = _line()

    assert line.network == "unknown"
    assert line.facility_in_network is None
    assert line.emergency is False
    assert line.preventive is False
    assert line.provider_type == "other"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("in", "in"),
        ("In-Network", "in"),
        ("out", "out"),
        ("out-of-network", "out"),
        ("OUT OF NETWORK", "out"),
        ("maybe", "unknown"),
        (None, "unknown"),
        (3, "unknown"),
    ],
)
def test_network_is_read_leniently(raw: object, expected: str) -> None:
    assert _line(network=raw).network == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("anesthesiology", "anesthesiology"),
        ("Anesthesiologist", "anesthesiology"),
        ("air ambulance", "air_ambulance"),
        ("Emergency-Medicine", "emergency_medicine"),
        ("hospital", "facility"),
        ("lab", "laboratory"),
        ("chiropractor", "other"),
        (None, "other"),
    ],
)
def test_provider_type_is_read_leniently(raw: object, expected: str) -> None:
    assert _line(provider_type=raw).provider_type == expected


@pytest.mark.parametrize(
    "raw,expected",
    [(True, True), ("yes", True), ("false", False), (None, None), ("unknown", None)],
)
def test_facility_network_keeps_unknown_as_null(raw: object, expected: bool | None) -> None:
    assert _line(facility_in_network=raw).facility_in_network is expected


@pytest.mark.parametrize("raw,expected", [(True, True), ("yes", True), (None, False), ("?", False)])
def test_emergency_and_preventive_default_to_false(raw: object, expected: bool) -> None:
    line = _line(emergency=raw, preventive=raw)
    assert line.emergency is expected
    assert line.preventive is expected


def test_odd_details_never_drop_a_charge() -> None:
    items = _parse_line_items(
        [{**_BASE, "network": "sideways", "provider_type": 7, "facility_in_network": "idk"}]
    )

    assert len(items) == 1
    assert items[0].billed == 2400


def test_gemini_is_asked_for_every_detail_with_the_same_choices() -> None:
    line = _EOB_SCHEMA["properties"]["line_items"]["items"]
    properties, required = line["properties"], line["required"]

    assert properties["network"]["enum"] == list(get_args(Network))
    assert properties["provider_type"]["enum"] == list(get_args(ProviderType))
    assert properties["facility_in_network"]["nullable"] is True
    assert {"network", "emergency", "preventive", "provider_type"} <= set(required)
    for field in ("network", "facility_in_network", "emergency", "preventive", "provider_type"):
        assert field in _EOB_INSTRUCTION


def test_offline_sample_bill_is_in_network_preventive_care(client: TestClient) -> None:
    pdf = (SAMPLES_DIR / "sample-bill.pdf").read_bytes()
    scan = client.post(
        "/api/eob/scan", files={"file": ("sample-bill.pdf", pdf, "application/pdf")}
    ).json()

    for line in scan["line_items"]:
        assert line["network"] == "in"
        assert line["preventive"] is True
        assert line["emergency"] is False
        assert line["provider_type"] == "primary_care"


def test_scan_returns_and_saves_the_details(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    reply = {
        "is_medical_bill": True,
        "provider": "Valley Anesthesia Associates",
        "total_billed": 2400,
        "line_items": [
            {
                **_BASE,
                "plan_expected": 480,
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
    saved = client.get(f"/api/eob/scans/{scan['scan_id']}").json()

    for body in (scan, saved):
        [line] = body["line_items"]
        assert line["network"] == "out"
        assert line["facility_in_network"] is True
        assert line["provider_type"] == "anesthesiology"
