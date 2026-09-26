"""Endpoints for ingesting benefits documents into the vector store."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.dependencies import AppServices, get_services
from app.schemas import DocumentIngestRequest, DocumentIngestResponse
from app.services.ingestion import chunk_text, extract_pdf_text
from app.services.vector_store import Chunk

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _ingest(services: AppServices, title: str, text: str) -> DocumentIngestResponse:
    chunks = chunk_text(text)
    if not chunks:
        raise HTTPException(status_code=400, detail="Document contained no text.")
    embeddings = services.gemini.embed_texts(chunks)
    records = [
        Chunk(document=title, text=chunk, embedding=embedding)
        for chunk, embedding in zip(chunks, embeddings, strict=True)
    ]
    added = services.vector_store.add(records)
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
