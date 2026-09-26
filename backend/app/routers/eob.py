"""EOB / medical bill scanner endpoint (Gemini vision)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.dependencies import AppServices, get_services
from app.schemas import EobLineItem, EobScanResponse
from app.services.vector_store import SearchHit

_ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "application/pdf"}


router = APIRouter(prefix="/api/eob", tags=["eob"])


def _policy_context(services: AppServices) -> str:
    """Pull a few high-level plan excerpts to ground coverage decisions."""
    probe = services.gemini.embed_query(
        "coverage deductible coinsurance preventive duplicate billing"
    )
    hits: list[SearchHit] = services.vector_store.search(probe, k=3)
    return "\n\n".join(hit.text for hit in hits)


@router.post("/scan", response_model=EobScanResponse)
async def scan_eob(
    file: UploadFile = File(...),
    services: AppServices = Depends(get_services),
) -> EobScanResponse:
    if file.content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Upload a PNG, JPEG, WEBP image or PDF of your bill/EOB.",
        )
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file was empty.")

    result = services.gemini.analyze_eob(
        image_bytes=data,
        mime_type=file.content_type or "image/png",
        policy_context=_policy_context(services),
    )

    line_items = [EobLineItem(**item) for item in result.get("line_items", [])]
    return EobScanResponse(
        provider=result.get("provider"),
        total_billed=result.get("total_billed", 0.0),
        line_items=line_items,
        overcharge_flags=result.get("overcharge_flags", []),
        summary=result.get("summary", ""),
        demo_mode=not services.gemini.enabled,
    )
