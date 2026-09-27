"""The patient rights rules must be complete, unique, and cite official sources."""

from __future__ import annotations

import json
import re
from importlib.resources import files
from urllib.parse import urlparse

import pytest

FIELDS = {
    "id",
    "title",
    "explanation",
    "you_should_owe",
    "action",
    "source_name",
    "citation_url",
}
OFFICIAL_HOSTS = {"www.healthcare.gov", "www.cms.gov", "www.consumerfinance.gov"}
EXPECTED_IDS = {
    "preventive_care",
    "nsa_emergency",
    "nsa_ancillary",
    "nsa_air_ambulance",
    "ground_ambulance",
    "duplicate_charge",
    "appeal_right",
}


def _rules() -> list[dict]:
    return json.loads(files("app.data").joinpath("patient_rights.json").read_text("utf-8"))


RULES = _rules()


def test_file_is_a_list_of_the_expected_rules() -> None:
    assert isinstance(RULES, list)
    ids = [rule["id"] for rule in RULES]
    assert len(ids) == len(set(ids))
    assert set(ids) == EXPECTED_IDS


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r["id"])
def test_rule_has_exactly_the_expected_non_empty_fields(rule: dict) -> None:
    assert set(rule) == FIELDS
    for field in FIELDS:
        assert isinstance(rule[field], str)
        assert rule[field] == rule[field].strip()
        assert rule[field]


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r["id"])
def test_rule_id_is_snake_case(rule: dict) -> None:
    assert re.fullmatch(r"[a-z]+(_[a-z]+)*", rule["id"])


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r["id"])
def test_rule_cites_an_official_https_source(rule: dict) -> None:
    url = urlparse(rule["citation_url"])
    assert url.scheme == "https"
    assert url.netloc in OFFICIAL_HOSTS
    assert not any(ch.isspace() for ch in rule["citation_url"])


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r["id"])
def test_rule_text_fits_on_a_phone_card(rule: dict) -> None:
    assert len(rule["title"]) <= 90
    assert len(rule["explanation"]) <= 400
    assert len(rule["action"]) <= 250


def test_ground_ambulance_does_not_promise_protection() -> None:
    rule = next(r for r in RULES if r["id"] == "ground_ambulance")
    assert "isn't covered" in rule["title"]
    assert "Possibly more" in rule["you_should_owe"]


def test_no_surprises_rules_cap_at_in_network_cost_sharing() -> None:
    for rule_id in ("nsa_emergency", "nsa_ancillary", "nsa_air_ambulance"):
        rule = next(r for r in RULES if r["id"] == rule_id)
        assert "in-network" in rule["you_should_owe"]
        assert "No Surprises Act" in rule["explanation"] + rule["action"]
