"""EOB / medical bill scanner endpoint (Gemini vision)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import ValidationError

from app.dependencies import AppServices, get_services, require_plan
from app.schemas import EobLineItem, EobScanResponse
from app.services.gemini import GeminiUnavailableError

logger = logging.getLogger("clearclaim.eob")

_ALLOWED_IMAGE_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/heic",
    "image/heif",
    "application/pdf",
}
_MAX_UPLOAD_BYTES = 15 * 1024 * 1024
_FULLY_COVERED_FLAG = "Your plan should cover this in full, so you shouldn't be charged."


router = APIRouter(prefix="/api/eob", tags=["eob"])


def _policy_context(services: AppServices) -> str:
    """Pull a few high-level plan excerpts to ground coverage decisions."""
    try:
        probe = services.gemini.embed_query(
            "coverage deductible coinsurance preventive duplicate billing"
        )
    except GeminiUnavailableError:
        logger.exception("Policy retrieval unavailable; scanning without plan context")
        return ""
    return "\n\n".join(hit.text for hit in services.vector_store.search(probe, k=3))


def _parse_line_items(raw_items: object) -> list[EobLineItem]:
    """Keep every well-formed line item; skip malformed ones instead of failing the scan."""
    if not isinstance(raw_items, list):
        return []
    items: list[EobLineItem] = []
    for raw in raw_items:
        try:
            item = EobLineItem.model_validate(raw)
        except ValidationError:
            logger.warning("Skipping malformed EOB line item: %r", raw)
            continue
        if not item.flag and item.covered and item.plan_expected == 0 and item.billed > 0:
            item.flag = _FULLY_COVERED_FLAG
        items.append(item)
    return items


def potential_savings(items: list[EobLineItem]) -> float:
    """Money at risk: for each flagged line, what was billed beyond what the plan expects."""
    total = sum(
        max(item.billed - (item.plan_expected or 0.0), 0.0) for item in items if item.flag
    )
    return round(total, 2)


@router.post("/scan", response_model=EobScanResponse)
async def scan_eob(
    file: UploadFile = File(...),
    services: AppServices = Depends(get_services),
) -> EobScanResponse:
    require_plan(services)
    if file.content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Upload a photo (PNG, JPEG, WEBP, HEIC) or PDF of your bill/EOB.",
        )
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file was empty.")
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File is too large (15 MB max).")

    result = services.gemini.analyze_eob(
        image_bytes=data,
        mime_type=file.content_type or "image/png",
        policy_context=_policy_context(services),
    )

    raw_flags = result.data.get("overcharge_flags")
    flags = [str(f) for f in raw_flags if f] if isinstance(raw_flags, list) else []
    line_items = _parse_line_items(result.data.get("line_items"))
    flags += [
        f"{item.description} ({item.code}): {item.flag}"
        for item in line_items
        if item.flag == _FULLY_COVERED_FLAG
    ]
    return EobScanResponse(
        provider=result.data.get("provider") or None,
        total_billed=float(result.data.get("total_billed") or 0.0),
        line_items=line_items,
        overcharge_flags=flags,
        potential_savings=potential_savings(line_items),
        summary=str(result.data.get("summary") or ""),
        demo_mode=not result.live,
    )
