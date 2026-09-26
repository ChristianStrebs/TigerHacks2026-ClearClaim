"""Thin wrapper around the Google Gen AI (Gemini) SDK.

When no API key is configured the service transparently falls back to
deterministic, offline behavior so the whole product is demoable without
network access or secrets. Live calls that fail (bad key, overloaded model,
network drop) first retry on backup models, then fall back instead of
surfacing a 500. Every result reports whether it actually came from Gemini so
the UI can stay honest.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import NamedTuple

from google import genai
from google.genai import types

from app.config import Settings
from app.services.benefits import extract_plan_numbers_offline

logger = logging.getLogger("clearclaim.gemini")

_MAX_PLAN_CHARS = 40_000

_PLAN_INSTRUCTION = """You read health insurance benefit documents: Summaries of Benefits and
Coverage, plan booklets, and photos of benefits pages or cards.
Extract the member's in-network, individual numbers:
- deductible: the annual deductible in dollars
- coinsurance_percent: the member's share after the deductible, as a percent (20 means 20%)
- oop_max: the annual out-of-pocket maximum in dollars
Use 0 for any number the document does not state. Never guess.
Write `summary` as 4-6 markdown "- " bullets in plain language (8th-grade reading level):
deductible, coinsurance, out-of-pocket max, free preventive care, common copays, and the
biggest watch-outs such as prior authorization. Financial and administrative only; no
medical advice.
If the input is an image or a scanned document, put a faithful plain-text transcription of
every benefit detail in `full_text`; otherwise use an empty string."""

_UNREADABLE_PHOTO_SUMMARY = (
    "I couldn't read this photo right now because the AI service is unavailable. "
    "Try again in a moment, or upload a PDF of your benefits."
)

_TOKEN = re.compile(r"[a-z0-9]+")

_EOB_INSTRUCTION = (
    "You are a medical billing expert. Extract every line item from this "
    "Explanation of Benefits or medical bill. For each line item return the "
    "billing/CPT code, a short description, the billed amount, the amount the "
    "member should owe under their plan (plan_expected), whether the plan should "
    "cover it, and a flag string when the charge looks like a duplicate, an "
    "upcode, or something the plan should have covered. Use an empty string for "
    "flag when the line looks fine. Use the provided plan summary to decide "
    "coverage. Write the summary in plain language. Respond ONLY with JSON."
)

_CHAT_INSTRUCTION = """You are ClearClaim, a friendly healthcare benefits copilot for employees.
- When policy excerpts are relevant, answer from them and be concrete about dollar
  amounts and deductible status.
- When the member asks a general question about employee health benefits (what a
  deductible is, how coinsurance works, HSA vs FSA, open enrollment), explain it
  clearly in general terms and note that exact numbers depend on their plan.
- When the question needs plan details that are not in the excerpts, say so plainly
  and invite them to submit their benefits with the + button.
- When a cost estimate is provided, use exactly those dollar figures; never recompute.
- Use plain language: short sentences, and define any insurance term the first time.
- Never give clinical or diagnostic medical advice; stay on administrative and
  financial topics.
- Keep answers under 180 words. Use only simple markdown: **bold** and "- " bullets."""

_OFFLINE_INVITE = (
    "Submit your benefits with the + button, or ask a general question about "
    "employee benefits, like \u201cWhat is a deductible?\u201d"
)

_GLOSSARY = {
    "deductible": (
        "A **deductible** is the amount you pay for covered care each year before "
        "your plan starts paying its share."
    ),
    "coinsurance": (
        "**Coinsurance** is the percentage of a bill you pay after your deductible "
        "is met. With 20% coinsurance, you pay $20 of every $100 and the plan pays $80."
    ),
    "copay": (
        "A **copay** is a flat fee, like $25, that you pay for a visit or prescription."
    ),
    "out-of-pocket": (
        "The **out-of-pocket maximum** is the most you pay for covered care in a year. "
        "After you hit it, the plan pays 100%."
    ),
    "premium": (
        "A **premium** is what you pay every paycheck or month just to have the "
        "plan, whether or not you use care."
    ),
}


class GeminiUnavailableError(RuntimeError):
    """Raised when a live embedding call fails and no safe fallback exists."""


class TextResult(NamedTuple):
    text: str
    live: bool


class EobResult(NamedTuple):
    data: dict
    live: bool


class PlanResult(NamedTuple):
    data: dict
    live: bool


class GeminiService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: genai.Client | None = None
        if settings.gemini_enabled:
            self._client = genai.Client(
                api_key=settings.gemini_api_key,
                http_options=types.HttpOptions(
                    timeout=int(settings.gemini_timeout_seconds * 1000)
                ),
            )
            logger.info("Gemini enabled with models %s", settings.gemini_generation_models)
        else:
            logger.warning(
                "GEMINI_API_KEY not set — running in DEMO MODE with offline "
                "deterministic responses."
            )

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def disable(self, reason: str) -> None:
        """Permanently switch to demo mode (used when startup indexing fails)."""
        logger.error("Disabling Gemini, falling back to demo mode: %s", reason)
        self._client = None

    def _generate(
        self, contents: types.ContentListUnion, config: types.GenerateContentConfig
    ) -> str | None:
        """Try the primary model, then each backup. Returns None if all fail."""
        if self._client is None:
            return None
        config.automatic_function_calling = types.AutomaticFunctionCallingConfig(disable=True)
        for model in self._settings.gemini_generation_models:
            try:
                response = self._client.models.generate_content(
                    model=model, contents=contents, config=config
                )
            except Exception as exc:
                logger.warning("Gemini model %s failed: %s", model, exc)
                continue
            text = (response.text or "").strip()
            if text:
                return text
            logger.warning("Gemini model %s returned an empty response", model)
        return None

    # ------------------------------------------------------------------ #
    # Embeddings
    # ------------------------------------------------------------------ #
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self._client is None:
            return [self._fallback_embedding(t) for t in texts]
        try:
            response = self._client.models.embed_content(
                model=self._settings.gemini_embed_model,
                contents=texts,
                config=types.EmbedContentConfig(
                    output_dimensionality=self._settings.embed_dim,
                    task_type="RETRIEVAL_DOCUMENT",
                ),
            )
        except Exception as exc:
            raise GeminiUnavailableError(f"Embedding documents failed: {exc}") from exc
        return [list(e.values) for e in response.embeddings]

    def embed_query(self, text: str) -> list[float]:
        if self._client is None:
            return self._fallback_embedding(text)
        try:
            response = self._client.models.embed_content(
                model=self._settings.gemini_embed_model,
                contents=text,
                config=types.EmbedContentConfig(
                    output_dimensionality=self._settings.embed_dim,
                    task_type="RETRIEVAL_QUERY",
                ),
            )
        except Exception as exc:
            raise GeminiUnavailableError(f"Embedding query failed: {exc}") from exc
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
    def generate_answer(
        self, question: str, context: str, benefits: str, cost_note: str | None = None
    ) -> TextResult:
        prompt = (
            f"Benefits snapshot:\n{benefits}\n\n"
            f"Policy excerpts:\n{context or '(none found)'}\n\n"
            + (f"Cost estimate (use these exact figures):\n{cost_note}\n\n" if cost_note else "")
            + f"Member question: {question}"
        )
        text = self._generate(
            prompt,
            types.GenerateContentConfig(system_instruction=_CHAT_INSTRUCTION, temperature=0.2),
        )
        if text is None:
            return TextResult(self._fallback_answer(question, context), live=False)
        return TextResult(text, live=True)

    def _fallback_answer(self, question: str, context: str) -> str:
        lowered = question.lower()
        definitions = [d for term, d in _GLOSSARY.items() if term in lowered]
        if definitions:
            return "\n\n".join([*definitions, _OFFLINE_INVITE])
        if not context.strip():
            return f"I don't have an answer for that yet. {_OFFLINE_INVITE}"
        snippet = context.strip().split("\n\n")[0][:400]
        return (
            "Here's the part of your plan that looks most relevant:\n\n"
            f"\u201c{snippet}\u2026\u201d\n\n{_OFFLINE_INVITE}"
        )

    # ------------------------------------------------------------------ #
    # Plan reading (benefits PDF text or photo)
    # ------------------------------------------------------------------ #
    def extract_plan(
        self,
        *,
        text: str = "",
        file_bytes: bytes = b"",
        mime_type: str = "",
    ) -> PlanResult:
        """Read plan numbers and a plain-language summary from text or an image/PDF."""
        contents: types.ContentListUnion
        if text.strip():
            contents = f"Benefits document text:\n{text[:_MAX_PLAN_CHARS]}"
        else:
            contents = [
                types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
                "Read this benefits document.",
            ]
        raw = self._generate(
            contents,
            types.GenerateContentConfig(
                system_instruction=_PLAN_INSTRUCTION,
                temperature=0.1,
                response_mime_type="application/json",
                response_schema=_PLAN_SCHEMA,
            ),
        )
        if raw is not None:
            try:
                return PlanResult(json.loads(raw), live=True)
            except json.JSONDecodeError:
                logger.exception("Gemini returned invalid plan JSON; using offline reader")
        if text.strip():
            return PlanResult(extract_plan_numbers_offline(text), live=False)
        return PlanResult({"summary": _UNREADABLE_PHOTO_SUMMARY}, live=False)

    # ------------------------------------------------------------------ #
    # Vision (EOB / bill scanner)
    # ------------------------------------------------------------------ #
    def analyze_eob(self, image_bytes: bytes, mime_type: str, policy_context: str) -> EobResult:
        text = self._generate(
            [
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                f"Plan summary to check coverage against:\n{policy_context}",
            ],
            types.GenerateContentConfig(
                system_instruction=_EOB_INSTRUCTION,
                temperature=0.1,
                response_mime_type="application/json",
                response_schema=_EOB_SCHEMA,
            ),
        )
        if text is None:
            return EobResult(self._fallback_eob(), live=False)
        try:
            return EobResult(json.loads(text), live=True)
        except json.JSONDecodeError:
            logger.exception("Gemini returned invalid EOB JSON; using sample analysis")
            return EobResult(self._fallback_eob(), live=False)

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
                "Sample analysis: this bill has two likely mistakes worth about $255 — "
                "a preventive blood draw that should be free and a duplicate office visit."
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

_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "plan_name": {"type": "string"},
        "deductible": {"type": "number"},
        "coinsurance_percent": {"type": "number"},
        "oop_max": {"type": "number"},
        "summary": {"type": "string"},
        "full_text": {"type": "string"},
    },
    "required": ["deductible", "coinsurance_percent", "oop_max", "summary", "full_text"],
}
