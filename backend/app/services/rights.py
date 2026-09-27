"""Which patient protections apply to a scanned bill.

Gemini only reads facts off the bill (network, emergency, provider type, and so on).
These plain rules decide which protection applies, so the same bill always gets the
same answer. The wording and sources live in ``app/data/patient_rights.json``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from functools import lru_cache
from importlib.resources import files
from typing import Any

from app.schemas import EobLineItem, RightsFinding

# Services the No Surprises Act protects at an in-network facility, even when the
# clinician who provided them is out of network.
_NSA_ANCILLARY = frozenset(
    {
        "emergency_medicine",
        "anesthesiology",
        "radiology",
        "pathology",
        "laboratory",
        "neonatology",
        "assistant_surgeon",
        "hospitalist",
        "intensivist",
    }
)
_AMBULANCES = frozenset({"air_ambulance", "ground_ambulance"})


@lru_cache(maxsize=1)
def _rules() -> dict[str, dict[str, Any]]:
    text = files("app.data").joinpath("patient_rights.json").read_text("utf-8")
    return {rule["id"]: rule for rule in json.loads(text)}


def _label(item: EobLineItem) -> str:
    return f"{item.description} ({item.code})" if item.code else item.description


def _preventive(item: EobLineItem) -> bool:
    return item.preventive and item.network == "in"


def _emergency(item: EobLineItem) -> bool:
    # Ambulances have their own rules; ground ambulances aren't protected at all.
    return (
        item.emergency
        and item.provider_type not in _AMBULANCES
        and (item.network == "out" or item.facility_in_network is False)
    )


def _ancillary(item: EobLineItem) -> bool:
    return (
        not _emergency(item)
        and item.provider_type in _NSA_ANCILLARY
        and item.network == "out"
        and item.facility_in_network is True
    )


def _air_ambulance(item: EobLineItem) -> bool:
    return item.provider_type == "air_ambulance" and item.network == "out"


def _ground_ambulance(item: EobLineItem) -> bool:
    return item.provider_type == "ground_ambulance" and item.network == "out"


def _denied(item: EobLineItem) -> bool:
    return not item.covered


_LINE_RULES: dict[str, Callable[[EobLineItem], bool]] = {
    "preventive_care": _preventive,
    "nsa_emergency": _emergency,
    "nsa_ancillary": _ancillary,
    "nsa_air_ambulance": _air_ambulance,
    "ground_ambulance": _ground_ambulance,
    "appeal_right": _denied,
}


def _duplicates(items: Sequence[EobLineItem]) -> list[EobLineItem]:
    """Every repeat of a charge already on the bill: same service, same amount."""
    seen: set[tuple[str, float]] = set()
    repeats = []
    for item in items:
        key = (item.code.strip().upper() or item.description.strip().lower(), item.billed)
        if key in seen:
            repeats.append(item)
        seen.add(key)
    return repeats


def check_rights(items: Sequence[EobLineItem]) -> list[RightsFinding]:
    """The protections that apply to these charges, in the order of the rules file."""
    charged = [item for item in items if item.billed > 0]
    repeats = _duplicates(charged)
    # A repeated charge is explained by the duplicate rule, not as a separate denial.
    originals = [item for item in charged if not any(item is r for r in repeats)]
    matches = {rule_id: [i for i in originals if test(i)] for rule_id, test in _LINE_RULES.items()}
    matches["duplicate_charge"] = repeats
    findings = []
    for rule_id, rule in _rules().items():
        lines = list(dict.fromkeys(_label(item) for item in matches.get(rule_id, [])))
        if lines:
            findings.append(
                RightsFinding(
                    rule_id=rule_id,
                    title=rule["title"],
                    explanation=rule["explanation"],
                    you_should_owe=rule["you_should_owe"],
                    action=rule["action"],
                    lines=lines,
                    source_name=rule["source_name"],
                    citation_url=rule["citation_url"],
                )
            )
    return findings
