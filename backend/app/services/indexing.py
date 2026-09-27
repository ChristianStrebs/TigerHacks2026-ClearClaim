"""Chunk, embed, and store benefits documents for retrieval."""

from __future__ import annotations

from importlib import resources

from app.dependencies import AppServices
from app.services.ingestion import chunk_text
from app.services.vector_store import Chunk


def load_sample_policy() -> str:
    return resources.files("app.data").joinpath("sample_policy.txt").read_text(encoding="utf-8")


def embed_document(services: AppServices, title: str, text: str) -> list[Chunk]:
    """Chunk and embed ``text`` without storing it.

    Raises ``ValueError`` for empty text and ``GeminiUnavailableError`` when live
    embedding fails.
    """
    chunks = chunk_text(text)
    if not chunks:
        raise ValueError("Document contained no text.")
    embeddings = services.gemini.embed_texts(chunks)
    return [
        Chunk(document=title, text=chunk, embedding=embedding)
        for chunk, embedding in zip(chunks, embeddings, strict=True)
    ]


def index_document(services: AppServices, title: str, text: str) -> int:
    """Index ``text`` alongside existing documents and return the chunks added."""
    return services.vector_store.add(embed_document(services, title, text))


def replace_index(services: AppServices, title: str, text: str) -> None:
    """Build embeddings first, then replace the index in one store operation."""
    records = embed_document(services, title, text)
    services.vector_store.replace(records)
