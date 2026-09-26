"""Endpoints for ingesting benefits documents into the vector store."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.dependencies import AppServices, get_services
from app.schemas import DocumentIngestRequest, DocumentIngestResponse
from app.services.gemini import GeminiUnavailableError
from app.services.indexing import index_document
from app.services.ingestion import extract_pdf_text

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _ingest(services: AppServices, title: str, text: str) -> DocumentIngestResponse:
    try:
        added = index_document(services, title, text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GeminiUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail="The AI service is unreachable right now. Please try again in a moment.",
        ) from exc
    return DocumentIngestResponse(
        title=title,
        chunks_indexed=added,
        total_chunks=services.vector_store.count(),
    )


@router.post("", response_model=DocumentIngestResponse)
def ingest_text(
    payload: DocumentIngestRequest,
    services: AppServices = Depends(get_services),
) -> DocumentIngestResponse:
    return _ingest(services, payload.title, payload.text)


@router.post("/upload", response_model=DocumentIngestResponse)
async def ingest_pdf(
    file: UploadFile = File(...),
    services: AppServices = Depends(get_services),
) -> DocumentIngestResponse:
    if file.content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Please upload a PDF file.")
    data = await file.read()
    try:
        text = extract_pdf_text(data)
    except Exception as exc:  # noqa: BLE001 - surface a clean 400 to the client
        raise HTTPException(status_code=400, detail=f"Could not read PDF: {exc}") from exc
    return _ingest(services, file.filename or "uploaded.pdf", text)
