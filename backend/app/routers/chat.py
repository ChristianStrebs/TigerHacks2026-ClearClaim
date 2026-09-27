"""Retrieval-augmented chat endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from app.dependencies import AppServices, get_services, require_plan
from app.schemas import ChatRequest, ChatResponse, Source
from app.services.benefits import (
    estimate_out_of_pocket,
    extract_dollar_amount,
    snapshot,
)
from app.services.gemini import GeminiUnavailableError
from app.services.vector_store import SearchHit

logger = logging.getLogger("clearclaim.chat")

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _retrieve(services: AppServices, question: str) -> list[SearchHit]:
    try:
        query_embedding = services.gemini.embed_query(question)
    except GeminiUnavailableError:
        logger.exception("Retrieval unavailable; answering without policy excerpts")
        return []
    return services.vector_store.search(query_embedding, k=4)


@router.post("", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    services: AppServices = Depends(get_services),
) -> ChatResponse:
    plan = require_plan(services)
    previous_question = next(
        (turn.text for turn in reversed(payload.history) if turn.role == "user"), ""
    )
    # Follow-ups like "what about a $5,000 one?" only make sense with the prior question.
    hits = _retrieve(services, f"{previous_question}\n{payload.message}".strip())

    context = "\n\n".join(f"[{hit.document}] {hit.text}" for hit in hits)
    benefits = snapshot(plan)
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

    billed_amount = payload.billed_amount
    if billed_amount is None:
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
    )

    sources = [
        Source(document=hit.document, snippet=hit.text[:280], score=round(hit.score, 4))
        for hit in hits
    ]

    return ChatResponse(
        answer=answer.text,
        sources=sources,
        benefits=benefits,
        cost_estimate=cost_estimate,
        demo_mode=not answer.live,
    )
