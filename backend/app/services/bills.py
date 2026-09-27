"""Bill math and turning saved bill scans into plain text the chat can reason about."""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.schemas import BenefitsSnapshot, EobLineItem, EobScanResponse
from app.services.benefits import estimate_out_of_pocket
from app.services.storage import MemberStore

_BILL_WORDS = re.compile(
    r"\b(bills?|charged|charges|duplicates?|double[- ]charged|disputes?|overcharged?)\b",
    re.IGNORECASE,
)


def mentions_bill(text: str) -> bool:
    return _BILL_WORDS.search(text) is not None


def deductible_from_bills(store: MemberStore) -> float:
    """How much every saved bill for the current plan paid toward the deductible.

    Only each bill's deductible portion counts; coinsurance never does.
    """
    return round(sum(entry.applied_to_deductible for entry in store.bill_ledger()), 2)


def member_cost(items: Sequence[EobLineItem], benefits: BenefitsSnapshot) -> float:
    """What the member should pay once flagged charges are fixed.

    Lines with an expected member cost use it. Lines without one are estimated from the
    plan's remaining deductible and coinsurance. Never more than the amount billed.
    """
    known = sum(item.plan_expected for item in items if item.plan_expected is not None)
    unknown = sum(item.billed for item in items if item.plan_expected is None)
    estimated = estimate_out_of_pocket(unknown, benefits).estimated_out_of_pocket if unknown else 0
    billed = sum(item.billed for item in items)
    return round(min(max(known + estimated, 0.0), billed), 2)


def describe_scan(scan: EobScanResponse) -> str:
    lines = [
        f"Bill from {scan.provider or 'an unknown provider'} (file: {scan.file_name}), "
        f"checked against {scan.plan_name}.",
        f"Total billed: ${scan.total_billed:,.2f}. "
        f"Member should pay: ${scan.you_owe:,.2f}. "
        f"Potential savings to question: ${scan.potential_savings:,.2f}.",
        "Line items:",
    ]
    for item in scan.line_items:
        expected = (
            f"member should pay ${item.plan_expected:,.2f}"
            if item.plan_expected is not None
            else "expected member cost unknown"
        )
        flag = f" Flag: {item.flag}" if item.flag else ""
        lines.append(
            f"- {item.code} {item.description}: billed ${item.billed:,.2f}, {expected}.{flag}"
        )
    if scan.rights:
        lines.append("Patient protections that may apply:")
        lines += [
            f"- {finding.title} (applies to: {', '.join(finding.lines)}). "
            f"Member should owe: {finding.you_should_owe} What to do: {finding.action} "
            f"Source: {finding.citation_url}"
            for finding in scan.rights
        ]
    if scan.summary:
        lines.append(f"Summary: {scan.summary}")
    return "\n".join(lines)


def describe_scans(scans: Sequence[EobScanResponse]) -> str:
    """The newest bill first, then earlier ones, so the chat can compare them."""
    if not scans:
        return ""
    latest, *earlier = scans
    parts = [describe_scan(latest)]
    parts += [f"Earlier bill {i}:\n{describe_scan(scan)}" for i, scan in enumerate(earlier, 1)]
    return "\n\n".join(parts)
