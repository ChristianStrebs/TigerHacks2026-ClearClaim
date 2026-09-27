"""Check that an upload's bytes match the file type it claims before any AI call."""

from __future__ import annotations

from collections.abc import Callable

UNREADABLE_FILE_DETAIL = (
    "This file couldn't be opened. It may be damaged, or it isn't really the PDF or photo "
    "its name says. Try saving it again, or take a new photo."
)


def _is_heif(data: bytes) -> bool:
    return data[4:8] == b"ftyp"


_SIGNATURES: dict[str, Callable[[bytes], bool]] = {
    # PDF readers accept the header anywhere in the first 1 KB.
    "application/pdf": lambda data: b"%PDF-" in data[:1024],
    "image/png": lambda data: data.startswith(b"\x89PNG\r\n\x1a\n"),
    "image/jpeg": lambda data: data.startswith(b"\xff\xd8\xff"),
    "image/webp": lambda data: data[:4] == b"RIFF" and data[8:12] == b"WEBP",
    "image/heic": _is_heif,
    "image/heif": _is_heif,
}


def matches_type(data: bytes, mime_type: str) -> bool:
    check = _SIGNATURES.get(mime_type)
    return check is not None and check(data)
