"""Deterministic out-of-pocket cost math based on a member's benefits."""

from __future__ import annotations

from app.config import Settings
from app.schemas import BenefitsSnapshot, CostEstimate


def current_benefits(settings: Settings) -> BenefitsSnapshot:
    remaining = max(settings.demo_deductible_total - settings.demo_deductible_met, 0.0)
    return BenefitsSnapshot(
        deductible_total=settings.demo_deductible_total,
        deductible_met=settings.demo_deductible_met,
        deductible_remaining=remaining,
        coinsurance_rate=settings.demo_coinsurance_rate,
        oop_max=settings.demo_oop_max,
    )


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
        f"then you pay {benefits.coinsurance_rate:.0%} coinsurance "
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
