"""The member's active plan profile plus deterministic out-of-pocket math."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Literal

from app.config import Settings
from app.schemas import (
    MAX_NAME_CHARS,
    BenefitsSnapshot,
    CostEstimate,
    PlanField,
    PlanResponse,
)

_DOLLAR_AMOUNT = re.compile(r"\$\s?(\d[\d,]*(?:\.\d{1,2})?)\s*(k\b)?", re.IGNORECASE)
_DEDUCTIBLE = re.compile(r"deductible[^$\n]{0,60}?\$\s?(\d[\d,]*)", re.IGNORECASE)
_OOP_MAX = re.compile(
    r"out[- ]of[- ]pocket\s+(?:max(?:imum)?|limit)[^$\n]{0,60}?\$\s?(\d[\d,]*)", re.IGNORECASE
)
_COINSURANCE = re.compile(
    r"(?<![\d.])(\d{1,3}(?:\.\d+)?)\s*%\s+coinsurance"
    r"|coinsurance[^%\n]{0,40}?(\d{1,3}(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)

_BENEFIT_TERMS = (
    "deductible",
    "coinsurance",
    "copay",
    "co-pay",
    "out-of-pocket",
    "out of pocket",
    "premium",
    "in-network",
    "preventive",
    "prior authorization",
    "summary of benefits",
    "health plan",
    "insurance",
)

SAMPLE_PLAN_NAME = "ACME Corp Health Plan (2026)"

_SAMPLE_SUMMARY = "\n".join(
    [
        "- **Deductible:** ${deductible:,.0f} a year. "
        "You pay this first, before the plan shares costs.",
        "- **Coinsurance:** after the deductible, you pay {member_percent:g}% "
        "and the plan pays {plan_percent:g}%.",
        "- **Out-of-pocket max:** ${oop_max:,.0f} a year. After that, covered care is free.",
        "- **Free preventive care:** wellness visits, shots, and screenings cost $0.",
        "- **Copays:** $25 primary care, $50 specialist, $10 generic drugs.",
        "- **Watch out:** knee surgery and similar procedures need prior approval, "
        "or you may owe a $500 penalty.",
    ]
)


@dataclass
class PlanProfile:
    name: str
    source: Literal["demo", "document"]
    deductible_total: float
    deductible_met: float
    coinsurance_rate: float
    oop_max: float
    summary: str
    summary_live: bool
    demo_fields: list[PlanField] = field(default_factory=list)


def sample_plan(settings: Settings) -> PlanProfile:
    """The bundled demo plan, loaded when the member chooses to try sample data."""
    return PlanProfile(
        name=SAMPLE_PLAN_NAME,
        source="demo",
        deductible_total=settings.demo_deductible_total,
        deductible_met=settings.demo_deductible_met,
        coinsurance_rate=settings.demo_coinsurance_rate,
        oop_max=settings.demo_oop_max,
        summary=_SAMPLE_SUMMARY.format(
            deductible=settings.demo_deductible_total,
            member_percent=settings.demo_coinsurance_rate * 100,
            plan_percent=(1 - settings.demo_coinsurance_rate) * 100,
            oop_max=settings.demo_oop_max,
        ),
        summary_live=False,
        demo_fields=["deductible_total", "coinsurance_rate", "oop_max"],
    )


def _nonnegative(value: object) -> float | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or value < 0
        or not math.isfinite(value)
    ):
        return None
    return float(value)


def _coinsurance_rate(percent: object) -> float | None:
    """coinsurance_percent is always a percentage: 1 means 1%, not a fraction."""
    value = _nonnegative(percent)
    if value is None or value > 100:
        return None
    return value / 100


def plan_from_extraction(
    settings: Settings, fallback_name: str, extracted: dict, summary_live: bool
) -> PlanProfile:
    """Build a profile from extracted numbers, keeping demo values for anything missing.

    A plan document never says how much the member has already paid, so the
    deductible starts at $0 met.
    """
    demo_fields: list[PlanField] = []

    deductible = _nonnegative(extracted.get("deductible"))
    if deductible is None:
        deductible = settings.demo_deductible_total
        demo_fields.append("deductible_total")

    coinsurance = _coinsurance_rate(extracted.get("coinsurance_percent"))
    if coinsurance is None:
        coinsurance = settings.demo_coinsurance_rate
        demo_fields.append("coinsurance_rate")

    oop_max = _nonnegative(extracted.get("oop_max"))
    if oop_max is None:
        oop_max = settings.demo_oop_max
        demo_fields.append("oop_max")

    name = str(extracted.get("plan_name") or "").strip() or fallback_name
    return PlanProfile(
        name=name[:MAX_NAME_CHARS].strip(),
        source="document",
        deductible_total=deductible,
        deductible_met=0.0,
        coinsurance_rate=coinsurance,
        oop_max=oop_max,
        summary=str(extracted.get("summary") or "").strip(),
        summary_live=summary_live,
        demo_fields=demo_fields,
    )


def extract_plan_numbers_offline(text: str) -> dict:
    """Best-effort regex extraction used when Gemini is unavailable."""

    def dollars(pattern: re.Pattern[str]) -> float | None:
        match = pattern.search(text)
        return float(match.group(1).replace(",", "")) if match else None

    coinsurance_match = _COINSURANCE.search(text)
    coinsurance = (
        float(coinsurance_match.group(1) or coinsurance_match.group(2))
        if coinsurance_match
        else None
    )
    extracted: dict = {
        "deductible": dollars(_DEDUCTIBLE),
        "coinsurance_percent": coinsurance,
        "oop_max": dollars(_OOP_MAX),
    }
    lowered = text.lower()
    extracted["is_benefits_document"] = any(v is not None for v in extracted.values()) or (
        sum(term in lowered for term in _BENEFIT_TERMS) >= 2
    )
    found = [
        f"- **Deductible:** ${extracted['deductible']:,.0f}"
        if extracted["deductible"] is not None
        else "",
        f"- **Coinsurance:** {coinsurance:g}%" if coinsurance is not None else "",
        f"- **Out-of-pocket max:** ${extracted['oop_max']:,.0f}"
        if extracted["oop_max"] is not None
        else "",
    ]
    lines = [line for line in found if line]
    extracted["summary"] = (
        "Here's what I could find in your plan:\n" + "\n".join(lines)
        if lines
        else "I saved your plan, but couldn't pick out the key numbers without the AI service."
    )
    return extracted


def snapshot(plan: PlanProfile, bills_owed: float = 0.0) -> BenefitsSnapshot:
    """The plan's numbers, with what the member owes on scanned bills counted toward the
    deductible. Payments only count until the deductible is met, so the running total is
    simply capped, whatever order the bills were scanned in."""
    met = min(plan.deductible_met + max(bills_owed, 0.0), plan.deductible_total)
    met = round(max(met, plan.deductible_met), 2)
    return BenefitsSnapshot(
        deductible_total=plan.deductible_total,
        deductible_met=met,
        deductible_remaining=round(max(plan.deductible_total - met, 0.0), 2),
        coinsurance_rate=plan.coinsurance_rate,
        oop_max=plan.oop_max,
        demo_fields=list(plan.demo_fields),
    )


def plan_response(plan: PlanProfile | None, bills_owed: float = 0.0) -> PlanResponse:
    if plan is None:
        return PlanResponse(
            plan_name=None, source="none", benefits=None, summary="", demo_mode=False
        )
    return PlanResponse(
        plan_name=plan.name,
        source=plan.source,
        benefits=snapshot(plan, bills_owed),
        summary=plan.summary,
        demo_mode=not plan.summary_live,
    )


def extract_dollar_amount(text: str) -> float | None:
    """Return the first dollar figure in ``text`` (e.g. "$18,000" or "$18k"), if any."""
    match = _DOLLAR_AMOUNT.search(text)
    if match is None:
        return None
    amount = float(match.group(1).replace(",", ""))
    if match.group(2):
        amount *= 1000
    return amount


def estimate_out_of_pocket(billed_amount: float, benefits: BenefitsSnapshot) -> CostEstimate:
    """Estimate member responsibility for an in-network billed amount.

    Simplified model: the member pays the remaining deductible first, then
    coinsurance on the balance, capped at the out-of-pocket maximum.
    """
    billed_amount = max(billed_amount, 0.0)
    applied_to_deductible = min(billed_amount, benefits.deductible_remaining)
    after_deductible = billed_amount - applied_to_deductible
    coinsurance = round(after_deductible * benefits.coinsurance_rate, 2)

    out_of_pocket = round(applied_to_deductible + coinsurance, 2)
    already_spent = benefits.deductible_met
    out_of_pocket = min(out_of_pocket, max(benefits.oop_max - already_spent, 0.0))

    explanation = (
        f"Of the ${billed_amount:,.2f} billed, ${applied_to_deductible:,.2f} goes "
        f"toward your remaining ${benefits.deductible_remaining:,.2f} deductible, "
        f"then you pay {benefits.coinsurance_rate * 100:g}% coinsurance "
        f"(${coinsurance:,.2f}) on the rest. Estimated cost to you: "
        f"${out_of_pocket:,.2f}."
    )
    return CostEstimate(
        billed_amount=billed_amount,
        applied_to_deductible=round(applied_to_deductible, 2),
        coinsurance=coinsurance,
        estimated_out_of_pocket=out_of_pocket,
        explanation=explanation,
    )
