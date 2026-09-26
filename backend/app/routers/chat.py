"""Retrieval-augmented chat endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.dependencies import AppServices, get_services
from app.schemas import ChatRequest, ChatResponse, Source
from app.services.benefits import current_benefits, estimate_out_of_pocket

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    services: AppServices = Depends(get_services),
) -> ChatResponse:
    query_embedding = services.gemini.embed_query(payload.message)
    hits = services.vector_store.search(query_embedding, k=4)

    context = "\n\n".join(f"[{hit.document}] {hit.text}" for hit in hits)
    benefits = current_benefits(services.settings)
    benefits_text = (
        f"Deductible: ${benefits.deductible_met:,.0f} of "
        f"${benefits.deductible_total:,.0f} met "
        f"(${benefits.deductible_remaining:,.0f} remaining). "
        f"Coinsurance: {benefits.coinsurance_rate:.0%}. "
        f"Out-of-pocket max: ${benefits.oop_max:,.0f}."
    )

    answer = services.gemini.generate_answer(payload.message, context, benefits_text)

    cost_estimate = None
    if payload.billed_amount is not None:
        cost_estimate = estimate_out_of_pocket(payload.billed_amount, benefits)

    sources = [
        Source(document=hit.document, snippet=hit.text[:280], score=round(hit.score, 4))
        for hit in hits
    ]

    return ChatResponse(
        answer=answer,
        sources=sources,
        benefits=benefits,
        cost_estimate=cost_estimate,
        demo_mode=not services.gemini.enabled,
    )
