"""Live Gemini smoke test. Run from ``backend/`` with ``python -m app.smoke``.

Exits non-zero if any live call falls back to demo mode, so you know before
judging whether the key and model names in ``.env`` actually work.
"""

from __future__ import annotations

import sys

from app.config import get_settings
from app.services.gemini import GeminiService, GeminiUnavailableError


def main() -> int:
    settings = get_settings()
    if not settings.gemini_enabled:
        print("GEMINI_API_KEY is not set in backend/.env; the app will run in demo mode.")
        return 1

    service = GeminiService(settings)
    print(f"Chat model:  {settings.gemini_chat_model}")
    print(f"Embed model: {settings.gemini_embed_model}")

    ok = True
    try:
        vector = service.embed_query("What is my deductible?")
        print(f"[PASS] embeddings ({len(vector)} dims)")
    except GeminiUnavailableError as exc:
        print(f"[FAIL] embeddings: {exc}")
        ok = False

    answer = service.generate_answer(
        "What is my deductible?",
        "Individual in-network deductible: $2,000 per plan year.",
        "Deductible: $450 of $2,000 met.",
    )
    print(f"[{'PASS' if answer.live else 'FAIL'}] chat: {answer.text[:120]!r}")
    ok = ok and answer.live

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
