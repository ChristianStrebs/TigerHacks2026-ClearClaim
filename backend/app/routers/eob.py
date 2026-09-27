"""EOB / medical bill scanner (Gemini vision) and the member's recent saved scans."""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import UTC, datetime
from functools import lru_cache

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError

from app.dependencies import AppServices, get_services, require_plan
from app.routers.samples import SAMPLES_DIR
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
NOT_A_BILL_DETAIL = (
    "This doesn't look like a medical bill or Explanation of Benefits. Try a photo or PDF "
    "of the bill from your doctor, hospital, or insurer."
)
NO_CHARGES_DETAIL = (
    "I couldn't find any charges on this file. Make sure the whole bill is in view and the "
    "amounts are readable, then try again."
)
AI_DOWN_DETAIL = (
    "I can't read your bill right now because the AI service is unavailable. Try again in "
    "a moment, or tap Try sample bill to see how it works."
)


@lru_cache(maxsize=1)
def _sample_bill_digest() -> str:
    return hashlib.sha256((SAMPLES_DIR / "sample-bill.pdf").read_bytes()).hexdigest()


def _is_sample_bill(data: bytes) -> bool:
    return hashlib.sha256(data).hexdigest() == _sample_bill_digest()


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
    plan = require_plan(services)
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

    # Gemini calls block, so keep them off the event loop.
    policy_context = await run_in_threadpool(_policy_context, services)
    result = await run_in_threadpool(
        services.gemini.analyze_eob,
        image_bytes=data,
        mime_type=file.content_type or "image/png",
        policy_context=policy_context,
    )
    # The offline result describes the sample bill, so never pass it off as the member's own.
    if not result.live and not _is_sample_bill(data):
        raise HTTPException(status_code=503, detail=AI_DOWN_DETAIL)
    if result.data.get("is_medical_bill") is False:
        raise HTTPException(status_code=422, detail=NOT_A_BILL_DETAIL)

    raw_flags = result.data.get("overcharge_flags")
    flags = [str(f) for f in raw_flags if f] if isinstance(raw_flags, list) else []
    line_items = _parse_line_items(result.data.get("line_items"))
    if not line_items:
        raise HTTPException(status_code=422, detail=NO_CHARGES_DETAIL)
    flags += [
        f"{item.description} ({item.code}): {item.flag}"
        for item in line_items
        if item.flag == _FULLY_COVERED_FLAG
    ]
    scan = EobScanResponse(
        scan_id=uuid.uuid4().hex,
        file_name=file.filename or "bill",
        scanned_at=datetime.now(UTC),
        plan_name=plan.name,
        provider=result.data.get("provider") or None,
        total_billed=float(result.data.get("total_billed") or 0.0),
        line_items=line_items,
        overcharge_flags=flags,
        potential_savings=potential_savings(line_items),
        summary=str(result.data.get("summary") or ""),
        demo_mode=not result.live,
    )
    # Don't save a scan checked against a plan the member has since replaced.
    if services.plan is plan:
        services.scans.append(scan)
    return scan


@router.get("/scans", response_model=list[EobScanResponse])
def list_scans(services: AppServices = Depends(get_services)) -> list[EobScanResponse]:
    """Saved scans for the current plan, newest first."""
    return list(reversed(services.scans))


@router.get("/scans/{scan_id}", response_model=EobScanResponse)
def get_scan(scan_id: str, services: AppServices = Depends(get_services)) -> EobScanResponse:
    for scan in services.scans:
        if scan.scan_id == scan_id:
            return scan
    raise HTTPException(status_code=404, detail="That bill scan isn't saved anymore.")


@router.delete("/scans", status_code=204)
def clear_scans(services: AppServices = Depends(get_services)) -> None:
    services.scans.clear()
