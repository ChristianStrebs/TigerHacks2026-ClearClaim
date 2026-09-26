"""Thin wrapper around the Google Gen AI (Gemini) SDK.

When no API key is configured the service transparently falls back to
deterministic, offline behavior so the whole product is demoable without
network access or secrets. Every fallback path is clearly marked so it is
obvious in the UI that the app is running in demo mode.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re

from app.config import Settings

logger = logging.getLogger("clearclaim.gemini")

_TOKEN = re.compile(r"[a-z0-9]+")

_EOB_INSTRUCTION = (
    "You are a medical billing expert. Extract every line item from this "
    "Explanation of Benefits or medical bill. For each line item return the "
    "billing/CPT code, a short description, the billed amount, whether the "
    "member's plan should cover it, and a flag string when the charge looks "
    "like a duplicate, an upcode, or something the plan should have covered. "
    "Use the provided plan summary to decide coverage. Respond ONLY with JSON."
)

_CHAT_INSTRUCTION = (
    "You are ClearClaim, a friendly healthcare benefits copilot. Answer the "
    "member's question using ONLY the provided policy excerpts and benefits "
    "snapshot. Be concrete about dollar amounts and deductible status. If the "
    "excerpts do not contain the answer, say so plainly. Never give clinical "
    "or diagnostic medical advice — stay on administrative and financial "
    "topics. Keep answers under 180 words."
)


class GeminiService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = None
        if settings.gemini_enabled:
            from google import genai

            self._client = genai.Client(api_key=settings.gemini_api_key)
            logger.info("Gemini enabled with model %s", settings.gemini_chat_model)
        else:
            logger.warning(
                "GEMINI_API_KEY not set — running in DEMO MODE with offline "
                "deterministic responses."
            )

    @property
    def enabled(self) -> bool:
        return self._client is not None

    # ------------------------------------------------------------------ #
    # Embeddings
    # ------------------------------------------------------------------ #
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self._client is None:
            return [self._fallback_embedding(t) for t in texts]

        from google.genai import types

        response = self._client.models.embed_content(
            model=self._settings.gemini_embed_model,
            contents=texts,
            config=types.EmbedContentConfig(
                output_dimensionality=self._settings.embed_dim,
                task_type="RETRIEVAL_DOCUMENT",
            ),
        )
        return [list(e.values) for e in response.embeddings]

    def embed_query(self, text: str) -> list[float]:
        if self._client is None:
            return self._fallback_embedding(text)

        from google.genai import types

        response = self._client.models.embed_content(
            model=self._settings.gemini_embed_model,
            contents=text,
            config=types.EmbedContentConfig(
                output_dimensionality=self._settings.embed_dim,
                task_type="RETRIEVAL_QUERY",
            ),
        )
        return list(response.embeddings[0].values)

    def _fallback_embedding(self, text: str) -> list[float]:
        """Deterministic hashed bag-of-words embedding for demo mode.

        Not semantically rich, but stable and good enough to make keyword-based
        retrieval work end-to-end without any external service.
        """
        dim = self._settings.embed_dim
        vec = [0.0] * dim
        for token in _TOKEN.findall(text.lower()):
            digest = hashlib.md5(token.encode()).digest()
            idx = int.from_bytes(digest[:4], "big") % dim
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[idx] += sign
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]

    # ------------------------------------------------------------------ #
    # Chat (RAG)
    # ------------------------------------------------------------------ #
    def generate_answer(self, question: str, context: str, benefits: str) -> str:
        if self._client is None:
            return self._fallback_answer(question, context)

        from google.genai import types

        prompt = (
            f"Benefits snapshot:\n{benefits}\n\n"
            f"Policy excerpts:\n{context}\n\n"
            f"Member question: {question}"
        )
        response = self._client.models.generate_content(
            model=self._settings.gemini_chat_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=_CHAT_INSTRUCTION,
                temperature=0.2,
            ),
        )
        return (response.text or "").strip()

    def _fallback_answer(self, question: str, context: str) -> str:
        if not context.strip():
            return (
                "[Demo mode] I couldn't find anything in your benefits documents "
                "about that yet. Add a Gemini API key to enable full AI answers."
            )
        snippet = context.strip().split("\n\n")[0][:400]
        return (
            "[Demo mode] Based on your plan documents, here's the most relevant "
            f"excerpt I found:\n\n\u201c{snippet}\u2026\u201d\n\n"
            "Add a GEMINI_API_KEY to get a fully synthesized answer with exact "
            "dollar figures."
        )

    # ------------------------------------------------------------------ #
    # Vision (EOB / bill scanner)
    # ------------------------------------------------------------------ #
    def analyze_eob(
        self, image_bytes: bytes, mime_type: str, policy_context: str
    ) -> dict:
        if self._client is None:
            return self._fallback_eob()

        from google.genai import types

        response = self._client.models.generate_content(
            model=self._settings.gemini_chat_model,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                f"Plan summary to check coverage against:\n{policy_context}",
            ],
            config=types.GenerateContentConfig(
                system_instruction=_EOB_INSTRUCTION,
                temperature=0.1,
                response_mime_type="application/json",
                response_schema=_EOB_SCHEMA,
            ),
        )
        try:
            return json.loads(response.text or "{}")
        except json.JSONDecodeError:
            logger.exception("Failed to parse EOB JSON from Gemini")
            return self._fallback_eob()

    def _fallback_eob(self) -> dict:
        return {
            "provider": "Mizzou Health Partners (sample)",
            "total_billed": 1240.00,
            "line_items": [
                {
                    "code": "99213",
                    "description": "Office visit, established patient",
                    "billed": 210.00,
                    "plan_expected": 165.00,
                    "covered": True,
                    "flag": None,
                },
                {
                    "code": "80053",
                    "description": "Comprehensive metabolic panel",
                    "billed": 130.00,
                    "plan_expected": 130.00,
                    "covered": True,
                    "flag": None,
                },
                {
                    "code": "36415",
                    "description": "Routine venipuncture (blood draw)",
                    "billed": 45.00,
                    "plan_expected": 0.00,
                    "covered": True,
                    "flag": "Preventive draw — should be $0 under your plan.",
                },
                {
                    "code": "99213",
                    "description": "Office visit (duplicate charge)",
                    "billed": 210.00,
                    "plan_expected": 0.00,
                    "covered": False,
                    "flag": "Possible duplicate of the first office visit.",
                },
            ],
            "overcharge_flags": [
                "Line 3: routine blood draw billed at $45 but preventive under your plan.",
                "Line 4: office visit 99213 appears twice — likely a duplicate charge.",
            ],
            "summary": (
                "[Demo mode] This sample EOB has two likely issues worth about "
                "$255. Add a GEMINI_API_KEY to scan your real bills with Gemini "
                "vision."
            ),
        }


# JSON schema handed to Gemini for structured EOB extraction.
_EOB_SCHEMA = {
    "type": "object",
    "properties": {
        "provider": {"type": "string"},
        "total_billed": {"type": "number"},
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "description": {"type": "string"},
                    "billed": {"type": "number"},
                    "plan_expected": {"type": "number"},
                    "covered": {"type": "boolean"},
                    "flag": {"type": "string"},
                },
                "required": ["code", "description", "billed", "covered"],
            },
        },
        "overcharge_flags": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
    },
    "required": ["total_billed", "line_items", "overcharge_flags", "summary"],
}
