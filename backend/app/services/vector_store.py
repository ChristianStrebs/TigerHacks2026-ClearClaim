"""Pluggable vector store used for retrieval-augmented generation.

Two backends are provided:

* :class:`InMemoryVectorStore` — zero-dependency cosine search, the default. It
  is ideal for local development and the hackathon demo.
* :class:`SupabaseVectorStore` — persists embeddings to Postgres/pgvector via
  Supabase and delegates similarity search to a SQL ``match_documents`` RPC.

Both implement :class:`VectorStore`, so the rest of the app is agnostic to
which one is active.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from threading import RLock
from typing import Protocol

import numpy as np
from supabase import create_client

from app.config import Settings

logger = logging.getLogger("clearclaim.vector_store")


class IndexReplacementError(RuntimeError):
    """The index could not be replaced; do not update the active plan."""


@dataclass
class Chunk:
    document: str
    text: str
    embedding: list[float]
    id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class SearchHit:
    document: str
    text: str
    score: float


class VectorStore(Protocol):
    backend_name: str

    def add(self, chunks: list[Chunk]) -> int: ...

    def search(self, query_embedding: list[float], k: int = 4) -> list[SearchHit]: ...

    def count(self) -> int: ...

    def clear(self) -> None: ...

    def replace(self, chunks: list[Chunk]) -> int: ...


def _cosine(matrix: np.ndarray, query: np.ndarray) -> np.ndarray:
    """Row-wise cosine similarity between ``matrix`` rows and ``query``."""
    matrix_norm = np.linalg.norm(matrix, axis=1)
    query_norm = np.linalg.norm(query)
    denom = matrix_norm * query_norm
    denom[denom == 0] = 1e-12
    return (matrix @ query) / denom


class InMemoryVectorStore:
    """A simple, dependency-light cosine-similarity store."""

    backend_name = "in-memory"

    def __init__(self) -> None:
        self._lock = RLock()
        self._chunks: list[Chunk] = []
        self._matrix: np.ndarray | None = None

    def add(self, chunks: list[Chunk]) -> int:
        if not chunks:
            return 0
        with self._lock:
            self.replace([*self._chunks, *chunks])
        return len(chunks)

    def replace(self, chunks: list[Chunk]) -> int:
        # Build/validate the matrix before publishing either piece of state.
        replacement = list(chunks)
        matrix = (
            np.array([c.embedding for c in replacement], dtype=np.float32) if replacement else None
        )
        with self._lock:
            self._chunks, self._matrix = replacement, matrix
        return len(replacement)

    def search(self, query_embedding: list[float], k: int = 4) -> list[SearchHit]:
        with self._lock:
            chunks, matrix = self._chunks, self._matrix
        if matrix is None or not chunks:
            return []
        query = np.array(query_embedding, dtype=np.float32)
        scores = _cosine(matrix, query)
        top = np.argsort(scores)[::-1][:k]
        return [
            SearchHit(document=chunks[i].document, text=chunks[i].text, score=float(scores[i]))
            for i in top
        ]

    def count(self) -> int:
        with self._lock:
            return len(self._chunks)

    def clear(self) -> None:
        self.replace([])


class SupabaseVectorStore:
    """pgvector-backed store using the Supabase Python client.

    Expects the schema created by ``supabase/migrations/0001_init.sql``: a
    ``documents`` table with a ``vector`` column and a ``match_documents`` RPC.
    """

    backend_name = "supabase-pgvector"

    def __init__(self, settings: Settings) -> None:
        self._client = create_client(settings.supabase_url, settings.supabase_service_role_key)

    def add(self, chunks: list[Chunk]) -> int:
        if not chunks:
            return 0
        rows = [
            {
                "id": c.id,
                "document": c.document,
                "content": c.text,
                "embedding": c.embedding,
            }
            for c in chunks
        ]
        self._client.table("documents").upsert(rows).execute()
        return len(chunks)

    def replace(self, chunks: list[Chunk]) -> int:
        rows = [
            {"id": c.id, "document": c.document, "content": c.text, "embedding": c.embedding}
            for c in chunks
        ]
        try:
            # One database transaction; never fall back to clear() followed by add().
            response = self._client.rpc("replace_documents", {"new_documents": rows}).execute()
        except Exception as exc:
            logger.exception("Atomic document replacement failed")
            raise IndexReplacementError(
                "Could not replace the plan index. Check the database connection and apply "
                "migration 0002_atomic_document_replacement.sql. Refresh the active plan "
                "before retrying; a connection timeout may leave the outcome unknown."
            ) from exc
        return int(response.data)

    def search(self, query_embedding: list[float], k: int = 4) -> list[SearchHit]:
        response = self._client.rpc(
            "match_documents",
            {"query_embedding": query_embedding, "match_count": k},
        ).execute()
        hits: list[SearchHit] = []
        for row in response.data or []:
            hits.append(
                SearchHit(
                    document=row.get("document", ""),
                    text=row.get("content", ""),
                    score=float(row.get("similarity", 0.0)),
                )
            )
        return hits

    def count(self) -> int:
        response = self._client.table("documents").select("id", count="exact").execute()
        return response.count or 0

    def clear(self) -> None:
        # PostgREST refuses unfiltered deletes, so match every row explicitly.
        self._client.table("documents").delete().not_.is_("id", "null").execute()


def create_vector_store(settings: Settings) -> VectorStore:
    """Return the configured vector store backend."""
    if settings.supabase_enabled:
        return SupabaseVectorStore(settings)
    return InMemoryVectorStore()
