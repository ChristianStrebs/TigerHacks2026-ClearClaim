"""Utilities for turning raw policy documents into retrievable chunks."""

from __future__ import annotations

import io
import re

from pypdf import PdfReader

_WHITESPACE = re.compile(r"\s+")
# Long unbroken runs (pasted URLs, base64, gibberish) would make chunks too large to embed or save.
_MAX_WORD_CHARS = 25


def clean_text(text: str) -> str:
    """Collapse whitespace so chunk boundaries are predictable."""
    return _WHITESPACE.sub(" ", text).strip()


def extract_pdf_text(data: bytes) -> str:
    """Extract plain text from a PDF byte string."""
    reader = PdfReader(io.BytesIO(data))
    pages = [page.extract_text() or "" for page in reader.pages]
    return clean_text("\n".join(pages))


def chunk_text(
    text: str,
    *,
    chunk_size: int = 140,
    overlap: int = 30,
) -> list[str]:
    """Split ``text`` into overlapping word windows.

    Overlap preserves context that would otherwise be cut across a boundary,
    which keeps retrieval quality high for policy documents that reference
    definitions defined paragraphs earlier.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be in [0, chunk_size)")

    words = [
        word[i : i + _MAX_WORD_CHARS]
        for word in clean_text(text).split(" ")
        for i in range(0, len(word), _MAX_WORD_CHARS)
    ]
    if not words:
        return []

    chunks: list[str] = []
    step = chunk_size - overlap
    for start in range(0, len(words), step):
        window = words[start : start + chunk_size]
        if not window:
            break
        chunks.append(" ".join(window))
        if start + chunk_size >= len(words):
            break
    return chunks
