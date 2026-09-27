"""The member's active plan: choose the sample, submit their own, or start over."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.dependencies import AppServices, get_services
from app.schemas import PlanResponse, PlanTextRequest
from app.services.benefits import (
    SAMPLE_PLAN_NAME,
    plan_from_extraction,
    plan_response,
    sample_plan,
)
from app.services.gemini import GeminiUnavailableError
from app.services.indexing import load_sample_policy, replace_index
from app.services.ingestion import extract_pdf_text
from app.services.vector_store import IndexReplacementError

router = APIRouter(prefix="/api/plan", tags=["plan"])

_PDF = "application/pdf"
_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/heic", "image/heif"}
_MAX_UPLOAD_BYTES = 15 * 1024 * 1024
_AI_UNREACHABLE = "The AI service is unreachable right now. Please try again in a moment."
NOT_BENEFITS_DETAIL = (
    "This doesn't look like a health insurance benefits document. Try your Summary of "
    "Benefits and Coverage, your plan booklet, or a photo of your benefits page."
)


def _apply_extracted_plan(
    services: AppServices,
    fallback_name: str,
    document_text: str,
    extracted: dict,
    summary_live: bool,
) -> PlanResponse:
    """Replace the active plan, or raise and leave the current plan untouched."""
    if extracted.get("is_benefits_document") is False:
        raise HTTPException(status_code=422, detail=NOT_BENEFITS_DETAIL)
    if not document_text.strip():
        raise HTTPException(
            status_code=422,
            detail=str(extracted.get("summary") or "Couldn't find any text to read."),
        )
    plan = plan_from_extraction(
        services.settings,
        fallback_name=fallback_name,
        extracted=extracted,
        summary_live=summary_live,
    )
    try:
        replace_index(services, plan.name, document_text)
    except GeminiUnavailableError as exc:
        raise HTTPException(status_code=503, detail=_AI_UNREACHABLE) from exc
    except IndexReplacementError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    services.plan = plan
    return plan_response(plan)


@router.get("", response_model=PlanResponse)
def get_plan(services: AppServices = Depends(get_services)) -> PlanResponse:
    return plan_response(services.plan)


@router.post("/text", response_model=PlanResponse)
def ingest_plan_text(
    payload: PlanTextRequest,
    services: AppServices = Depends(get_services),
) -> PlanResponse:
    """Paste policy text: extract numbers, write a plain-English summary, replace the index."""
    extraction = services.gemini.extract_plan(text=payload.text)
    document_text = payload.text or str(extraction.data.get("full_text") or "")
    return _apply_extracted_plan(
        services,
        fallback_name=payload.title,
        document_text=document_text,
        extracted=extraction.data,
        summary_live=extraction.live,
    )


@router.post("/upload", response_model=PlanResponse)
async def upload_plan(
    file: UploadFile = File(...),
    services: AppServices = Depends(get_services),
) -> PlanResponse:
    mime_type = file.content_type or ""
    if mime_type != _PDF and mime_type not in _IMAGE_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Upload your benefits as a PDF or a photo (PNG, JPEG, WEBP, HEIC).",
        )
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file was empty.")
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File is too large (15 MB max).")

    text = ""
    if mime_type == _PDF:
        try:
            text = extract_pdf_text(data)
        except Exception as exc:  # noqa: BLE001 - surface a clean 400 to the client
            raise HTTPException(status_code=400, detail=f"Could not read PDF: {exc}") from exc

    # Text PDFs are sent as text; photos and scanned PDFs go to Gemini vision.
    extraction = services.gemini.extract_plan(text=text, file_bytes=data, mime_type=mime_type)
    return _apply_extracted_plan(
        services,
        fallback_name=file.filename or "Your plan",
        document_text=text or str(extraction.data.get("full_text") or ""),
        extracted=extraction.data,
        summary_live=extraction.live,
    )


@router.post("/sample", response_model=PlanResponse)
@router.post("/reset", response_model=PlanResponse, include_in_schema=False)
def use_sample_plan(services: AppServices = Depends(get_services)) -> PlanResponse:
    """Load the bundled sample plan when the member chooses to try sample data."""
    try:
        replace_index(services, SAMPLE_PLAN_NAME, load_sample_policy())
    except GeminiUnavailableError as exc:
        raise HTTPException(status_code=503, detail=_AI_UNREACHABLE) from exc
    except IndexReplacementError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    services.plan = sample_plan(services.settings)
    return plan_response(services.plan)


@router.post("/clear", response_model=PlanResponse)
def clear_plan(services: AppServices = Depends(get_services)) -> PlanResponse:
    """Start over: forget the active plan so the app asks the member to choose again."""
    services.vector_store.clear()
    services.plan = None
    return plan_response(None)
