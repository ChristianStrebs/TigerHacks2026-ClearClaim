"""A dispute kit for a saved bill: a letter, a call script, a checklist, and timing."""

from __future__ import annotations

import logging

from pydantic import ValidationError

from app.schemas import DisputeKit, EobScanResponse
from app.services.bills import describe_scan
from app.services.gemini import GeminiService

logger = logging.getLogger("clearclaim.dispute")

_SURPRISE_BILL_RULES = {"nsa_emergency", "nsa_ancillary", "nsa_air_ambulance"}
NO_SURPRISES_HELP_DESK = "1-800-985-3059"


def dispute_kit(gemini: GeminiService, scan: EobScanResponse, plan_excerpts: str) -> DisputeKit:
    """Gemini's draft when it's usable, otherwise the template, so there's always a kit."""
    result = gemini.draft_dispute(describe_scan(scan), plan_excerpts)
    if result.live:
        try:
            kit = DisputeKit.model_validate({**result.data, "demo_mode": False})
        except ValidationError:
            logger.warning("Gemini's dispute kit was incomplete; using the template")
        else:
            if kit.letter.strip() and kit.call_script and kit.checklist:
                return kit
            logger.warning("Gemini's dispute kit was empty; using the template")
    return template_kit(scan)


def _money(amount: float) -> str:
    return f"${amount:,.2f}"


def template_kit(scan: EobScanResponse) -> DisputeKit:
    """A kit filled in from the scan alone, with [bracketed] parts for the member."""
    provider = scan.provider or "the provider"
    flagged = [item for item in scan.line_items if item.flag]
    rule_ids = {finding.rule_id for finding in scan.rights}
    disputed = bool(flagged or scan.rights)

    letter = [
        "[Today's date]",
        "[Your name]\n[Your address]",
        f"{provider}\nBilling Office",
        "Re: Request to review and correct my bill\n"
        "Account number: [Account number]\n"
        "Date of service: [Date of service]\n"
        "Insurance member ID: [Member ID]",
        "To whom it may concern:",
        f"I'm writing about my bill from {provider} for {_money(scan.total_billed)}. "
        f"I compared it with my health plan ({scan.plan_name}), and "
        + ("these charges look wrong:" if flagged else "I'd like to make sure it's correct."),
    ]
    if flagged:
        letter.append(
            "\n".join(
                f"- {item.description} ({item.code}), billed {_money(item.billed)}: {item.flag}"
                for item in flagged
            )
        )
    if scan.rights:
        letter.append("These patient protections may apply:")
        letter.append(
            "\n".join(
                f"- {finding.title}. What I should owe: {finding.you_should_owe} "
                f"Source: {finding.source_name}, {finding.citation_url}"
                for finding in scan.rights
            )
        )
    if scan.you_owe < scan.total_billed:
        letter.append(
            f"Based on my plan, I expect to owe about {_money(scan.you_owe)}, "
            f"not {_money(scan.total_billed)}."
        )
    letter += [
        "Please review these charges, send me a corrected, itemized bill, and hold my account "
        "so it isn't sent to collections while the review is open. Please reply in writing "
        "within 30 days.",
        "Thank you,\n[Your name]\n[Phone number]",
    ]

    call_script = [
        "Hi, I'm calling about a bill. My name is [Your name], and my account number is "
        "[Account number].",
        f"The bill is from {provider} for {_money(scan.total_billed)}, and "
        + ("I think some charges are wrong." if disputed else "I'd like to go over the charges."),
        *(
            f"{item.description} ({item.code}) was billed {_money(item.billed)}. {item.flag}"
            for item in flagged
        ),
        *(
            f"I believe this protection applies: {finding.title}. "
            f"What I should owe: {finding.you_should_owe}"
            for finding in scan.rights
        ),
        "Can you review these charges and send me a corrected, itemized bill?",
        "Can you hold my account so it doesn't go to collections while you review it?",
        "May I have your name and a reference number for this call?",
    ]

    checklist = [
        "Find your account number and date of service on the bill.",
        "Compare the bill with the Explanation of Benefits from your insurer.",
        "Call the billing office with the script. Write down the date, who you spoke with, "
        "and the reference number.",
        "Fill in the [bracketed] parts of the letter, send it, and keep a copy.",
    ]
    if rule_ids & _SURPRISE_BILL_RULES:
        checklist.append(
            "If the provider won't fix a surprise bill, call the No Surprises Help Desk at "
            f"{NO_SURPRISES_HELP_DESK}."
        )
    if "appeal_right" in rule_ids:
        checklist.append(
            "If your insurer denied a charge, file an internal appeal within 180 days of the "
            "denial notice."
        )
    checklist.append("Follow up if you haven't heard back in 30 days.")

    deadline_note = (
        "There's no single deadline for fixing a billing error, so act soon and ask the billing "
        "office to hold your account while they review it."
    )
    if "appeal_right" in rule_ids:
        deadline_note += " To appeal a denied claim, you have 180 days from the denial notice."

    return DisputeKit(
        letter="\n\n".join(letter),
        call_script=call_script,
        checklist=checklist,
        deadline_note=deadline_note,
        demo_mode=True,
    )
