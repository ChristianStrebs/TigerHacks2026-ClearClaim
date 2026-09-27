"""The member's active plan: choose the sample, submit their own, or start over."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from app.dependencies import AppServices, get_services, member_store
from app.schemas import PlanResponse, PlanTextRequest
from app.services.benefits import (
    PlanProfile,
    plan_from_extraction,
    plan_response,
    sample_plan,
)
from app.services.gemini import GeminiUnavailableError
from app.services.indexing import embed_document, load_sample_policy
from app.services.ingestion import extract_pdf_text
from app.services.storage import MemberStore

router = APIRouter(prefix="/api/plan", tags=["plan"])

_PDF = "application/pdf"
_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/heic", "image/heif"}
_MAX_UPLOAD_BYTES = 15 * 1024 * 1024
_AI_UNREACHABLE = "The AI service is unreachable right now. Please try again in a moment."
NOT_BENEFITS_DETAIL = (
    "This doesn't look like a health insurance benefits document. Try your Summary of "
    "Benefits and Coverage, your plan booklet, or a photo of your benefits page."
)
UNREADABLE_PDF_DETAIL = (
    "This PDF couldn't be opened. It may be damaged or password-protected. Try saving it "
    "again as a PDF, or upload a photo of your benefits page."
)


def _save_plan(
    services: AppServices, store: MemberStore, plan: PlanProfile, document_text: str
) -> PlanResponse:
    """Embed first, then swap the plan in one step so a failure keeps the current plan."""
    try:
        chunks = embed_document(services.gemini, plan.name, document_text)
    except GeminiUnavailableError as exc:
        raise HTTPException(status_code=503, detail=_AI_UNREACHABLE) from exc
    saved = store.replace_plan(plan, chunks, services.gemini.embedding_space)
    return plan_response(saved.profile)


def _apply_extracted_plan(
    services: AppServices,
    store: MemberStore,
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
    return _save_plan(services, store, plan, document_text)


@router.get("", response_model=PlanResponse)
def get_plan(store: MemberStore = Depends(member_store)) -> PlanResponse:
    saved = store.get_plan()
    return plan_response(saved.profile if saved else None)


@router.post("/text", response_model=PlanResponse)
def ingest_plan_text(
    payload: PlanTextRequest,
    services: AppServices = Depends(get_services),
    store: MemberStore = Depends(member_store),
) -> PlanResponse:
    """Paste policy text: extract numbers, write a plain-English summary, replace the index."""
    extraction = services.gemini.extract_plan(text=payload.text)
    document_text = payload.text or str(extraction.data.get("full_text") or "")
    return _apply_extracted_plan(
        services,
        store,
        fallback_name=payload.title,
        document_text=document_text,
        extracted=extraction.data,
        summary_live=extraction.live,
    )


@router.post("/upload", response_model=PlanResponse)
async def upload_plan(
    file: UploadFile = File(...),
    services: AppServices = Depends(get_services),
    store: MemberStore = Depends(member_store),
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

    # PDF parsing, Gemini, embedding, and database calls block, so keep them off the event loop.
    return await run_in_threadpool(
        _read_uploaded_plan, services, store, data, mime_type, file.filename or "Your plan"
    )


def _read_uploaded_plan(
    services: AppServices, store: MemberStore, data: bytes, mime_type: str, file_name: str
) -> PlanResponse:
    text = ""
    if mime_type == _PDF:
        try:
            text = extract_pdf_text(data)
        except Exception as exc:  # noqa: BLE001 - surface a clean 400 to the client
            raise HTTPException(status_code=400, detail=UNREADABLE_PDF_DETAIL) from exc

    # Text PDFs are sent as text; photos and scanned PDFs go to Gemini vision.
    extraction = services.gemini.extract_plan(text=text, file_bytes=data, mime_type=mime_type)
    transcript = str(extraction.data.get("full_text") or "")
    return _apply_extracted_plan(
        services,
        store,
        fallback_name=file_name,
        document_text=max(text, transcript, key=len),
        extracted=extraction.data,
        summary_live=extraction.live,
    )


@router.post("/sample", response_model=PlanResponse)
@router.post("/reset", response_model=PlanResponse, include_in_schema=False)
def use_sample_plan(
    services: AppServices = Depends(get_services),
    store: MemberStore = Depends(member_store),
) -> PlanResponse:
    """Load the bundled sample plan when the member chooses to try sample data."""
    return _save_plan(services, store, sample_plan(services.settings), load_sample_policy())


@router.post("/clear", response_model=PlanResponse)
def clear_plan(store: MemberStore = Depends(member_store)) -> PlanResponse:
    """Start over: forget the plan, its scans, and its chats so the app asks again."""
    store.clear_plan()
    return plan_response(None)
