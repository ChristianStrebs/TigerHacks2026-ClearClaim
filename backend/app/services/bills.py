"""Turn a saved bill scan into plain text the chat can reason about."""

from __future__ import annotations

import re

from app.schemas import EobScanResponse

_BILL_WORDS = re.compile(
    r"\b(bills?|charged|charges|duplicates?|double[- ]charged|disputes?|overcharged?)\b",
    re.IGNORECASE,
)


def mentions_bill(text: str) -> bool:
    return _BILL_WORDS.search(text) is not None


def describe_scan(scan: EobScanResponse) -> str:
    lines = [
        f"Bill from {scan.provider or 'an unknown provider'} (file: {scan.file_name}), "
        f"checked against {scan.plan_name}.",
        f"Total billed: ${scan.total_billed:,.2f}. "
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
    if scan.summary:
        lines.append(f"Summary: {scan.summary}")
    return "\n".join(lines)
