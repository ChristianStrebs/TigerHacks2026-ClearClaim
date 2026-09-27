"""Retrieval-augmented chat endpoint and the member's saved conversation."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from app.dependencies import AppServices, get_services, member_store, require_plan
from app.schemas import ChatHistoryItem, ChatRequest, ChatResponse, Source
from app.services.benefits import (
    estimate_out_of_pocket,
    extract_dollar_amount,
    snapshot,
)
from app.services.bills import bills_owed, describe_scans, mentions_bill
from app.services.indexing import search_plan
from app.services.storage import MemberStore, PlanReplacedError

logger = logging.getLogger("clearclaim.chat")

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    services: AppServices = Depends(get_services),
    store: MemberStore = Depends(member_store),
) -> ChatResponse:
    saved = require_plan(store)
    plan = saved.profile
    previous_question = next(
        (turn.text for turn in reversed(payload.history) if turn.role == "user"), ""
    )
    # Follow-ups like "what about a $5,000 one?" only make sense with the prior question.
    hits = search_plan(
        services.gemini, store, saved, f"{previous_question}\n{payload.message}".strip()
    )

    context = "\n\n".join(f"[{hit.document}] {hit.text}" for hit in hits)
    benefits = snapshot(plan, bills_owed(store))
    plan_note = (
        "This is a sample demo plan; the member has not submitted their own benefits yet."
        if plan.source == "demo"
        else "The member submitted this plan themselves."
    )
    benefits_text = (
        f"Plan: {plan.name}. {plan_note} "
        f"Deductible: ${benefits.deductible_met:,.0f} of "
        f"${benefits.deductible_total:,.0f} met "
        f"(${benefits.deductible_remaining:,.0f} remaining). "
        f"Coinsurance: {benefits.coinsurance_rate * 100:g}%. "
        f"Out-of-pocket max: ${benefits.oop_max:,.0f}."
    )

    scans = store.list_scans()
    scan = scans[0] if scans else None
    billed_amount = payload.billed_amount
    # "Why was I charged $250 twice?" is about the scanned bill, not a procedure to estimate.
    if billed_amount is None and not (scan and mentions_bill(payload.message)):
        billed_amount = extract_dollar_amount(payload.message)
    cost_estimate = (
        estimate_out_of_pocket(billed_amount, benefits) if billed_amount is not None else None
    )

    answer = services.gemini.generate_answer(
        payload.message,
        context,
        benefits_text,
        cost_note=cost_estimate.explanation if cost_estimate else None,
        history=payload.history,
        bill=describe_scans(scans) or None,
    )

    sources = [
        Source(document=hit.document, snippet=hit.text[:280], score=round(hit.score, 4))
        for hit in hits
    ]

    response = ChatResponse(
        answer=answer.text,
        sources=sources,
        benefits=benefits,
        cost_estimate=cost_estimate,
        bill_scan_id=scan.scan_id if scan else None,
        demo_mode=not answer.live,
    )
    try:
        store.add_chat(saved.id, payload.message, response)
    except PlanReplacedError:
        logger.info("Not saving an answer about a plan the member has since replaced")
    return response


@router.get("/history", response_model=list[ChatHistoryItem])
def chat_history(store: MemberStore = Depends(member_store)) -> list[ChatHistoryItem]:
    """The conversation about the current plan, oldest first, so a refresh can restore it."""
    return [
        ChatHistoryItem(question=turn.question, response=turn.response)
        for turn in store.list_chat()
    ]
