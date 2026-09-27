"""Chunk and embed benefits documents for retrieval."""

from __future__ import annotations

import logging
from importlib import resources

from app.services.gemini import GeminiService, GeminiUnavailableError
from app.services.ingestion import chunk_text
from app.services.storage import Chunk, MemberStore, SavedPlan, SearchHit

logger = logging.getLogger("clearclaim.indexing")


def load_sample_policy() -> str:
    return resources.files("app.data").joinpath("sample_policy.txt").read_text(encoding="utf-8")


def embed_document(gemini: GeminiService, title: str, text: str) -> list[Chunk]:
    """Chunk and embed ``text`` without storing it.

    Raises ``ValueError`` for empty text and ``GeminiUnavailableError`` when live
    embedding fails.
    """
    chunks = chunk_text(text)
    if not chunks:
        raise ValueError("Document contained no text.")
    embeddings = gemini.embed_texts(chunks)
    return [
        Chunk(document=title, text=chunk, embedding=embedding)
        for chunk, embedding in zip(chunks, embeddings, strict=True)
    ]


def search_plan(
    gemini: GeminiService, store: MemberStore, plan: SavedPlan, query: str, k: int = 4
) -> list[SearchHit]:
    """Plan excerpts closest to ``query``; empty when search isn't possible right now."""
    if plan.embed_model != gemini.embedding_space:
        logger.warning(
            "Plan was indexed with %s but %s is running; answering without excerpts",
            plan.embed_model,
            gemini.embedding_space,
        )
        return []
    try:
        embedding = gemini.embed_query(query)
    except GeminiUnavailableError:
        logger.exception("Retrieval unavailable; answering without policy excerpts")
        return []
    return store.search(embedding, k=k)
