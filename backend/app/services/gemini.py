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
from collections.abc import Sequence
from typing import NamedTuple

from google import genai
from google.genai import types

from app.config import Settings
from app.schemas import ChatTurn
from app.services.benefits import extract_plan_numbers_offline
from app.services.bills import mentions_bill

logger = logging.getLogger("clearclaim.gemini")

_MAX_HISTORY_TURNS = 10

_MAX_PLAN_CHARS = 40_000
_MIN_TEXT_LAYER_CHARS = 200
# The Gemini API accepts at most 100 texts per embedding request.
_EMBED_BATCH_SIZE = 100

_PLAN_INSTRUCTION = """You read health insurance benefit documents: Summaries of Benefits and
Coverage, plan booklets, and photos of benefits pages or cards.
Extract the member's in-network, individual numbers:
- deductible: the annual deductible in dollars
- coinsurance_percent: the member's share after the deductible, as a percent (20 means 20%)
- oop_max: the annual out-of-pocket maximum in dollars
Use null for any number the document does not state. Zero is a valid stated value,
not a missing-value marker. coinsurance_percent is a whole percentage: 20 means 20%,
never 0.2. Never guess.
Write `summary` as 4-6 short bullet strings in plain language (8th-grade reading level):
deductible, coinsurance, out-of-pocket max, free preventive care, common copays, and the
biggest watch-outs such as prior authorization. Financial and administrative only; no
medical advice.
If the input is an image or a scanned document, put a faithful plain-text transcription of
every benefit detail in `full_text`; otherwise use an empty string.
Set is_benefits_document to false when the input is not a health insurance benefits
document (for example a recipe, receipt, resume, medical bill, or random photo); then use
null for every number and an empty summary."""

_UNREADABLE_PHOTO_SUMMARY = (
    "I couldn't read this photo right now because the AI service is unavailable. "
    "Try again in a moment, or upload a PDF of your benefits."
)

_TOKEN = re.compile(r"[a-z0-9]+")

_EOB_INSTRUCTION = """You are a medical billing expert. Extract every line item from this
Explanation of Benefits or medical bill. For each line return the billing/CPT code, a short
description, the billed amount, whether the plan should cover it, and plan_expected: what the
member should personally pay for that line under the plan summary provided.
- plan_expected is 0 for a duplicate of an earlier line and for services the plan covers at
  100% (for example in-network preventive care when the visit reason is preventive).
- Use the member's deductible status: the member pays charges in full until the remaining
  deductible is used up (unless the plan says a copay applies instead), then coinsurance.
  Work through the lines in order and carry the remaining deductible from line to line.
- Set flag to one short plain-language reason on EVERY line where the member is charged more
  than plan_expected because of a duplicate, an upcode, or coverage the plan owes. Use an
  empty string only when the charge is correct.
- overcharge_flags lists one plain-language sentence per flagged line.
- Stay consistent: if the summary says a charge should be covered, that line must be flagged.
- Set is_medical_bill to false when the file is not a medical bill, statement, or EOB (for
  example a recipe, a store receipt, a benefits booklet, or a random photo); then return no
  line items and a total of 0.
Write the summary in plain language (8th-grade reading level). Respond ONLY with JSON."""

_CHAT_INSTRUCTION = """You are ClearClaim, a friendly healthcare benefits copilot for employees.
- The benefits snapshot and policy excerpts ARE the member's plan. Answer from them
  directly and confidently, with concrete dollar amounts and deductible status. Never
  add disclaimers like "depending on your plan's exact rules" or "exact numbers depend
  on your plan": you already have their plan.
- For general questions (what a deductible is, how coinsurance works, HSA vs FSA),
  explain the idea in one or two sentences, then show what it means with their plan's
  numbers.
- If a specific detail truly isn't in the excerpts, name exactly what is missing (for
  example, "Your plan summary doesn't say whether copays count toward the deductible")
  and suggest confirming with HR or the insurer. Never guess or fill gaps with typical
  plan rules.
- Don't mention that the plan is a sample plan; the app already labels sample numbers.
- Earlier messages in the conversation are context for follow-up questions like "what
  about a $5,000 one?". Always use the current benefits snapshot, which may have changed.
- When a cost estimate is provided, use exactly those dollar figures; never recompute.
- A "Latest scanned bill" section is the member's most recent bill; any "Earlier bill"
  entries after it are older scans. Answer about the bill the member means, defaulting to
  the latest. For questions about their bill, charges, duplicates, or what to dispute,
  cite its line codes and dollar amounts, explain why each flagged line may be wrong, and
  suggest calling the provider's billing office or the insurer. Savings are possible, not
  guaranteed. "Member should pay" is what they owe once flagged charges are fixed.
- If they ask about a bill and no scanned bill is included, ask them to scan it on the
  Scan tab first.
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
    "copay": ("A **copay** is a flat fee, like $25, that you pay for a visit or prescription."),
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
                http_options=types.HttpOptions(timeout=int(settings.gemini_timeout_seconds * 1000)),
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

    @property
    def embedding_space(self) -> str:
        """Names the vectors this service produces; different spaces can't be compared."""
        model = self._settings.gemini_embed_model if self.enabled else "offline"
        return f"{model}:{self._settings.embed_dim}"

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
        embeddings: list[list[float]] = []
        for start in range(0, len(texts), _EMBED_BATCH_SIZE):
            try:
                response = self._client.models.embed_content(
                    model=self._settings.gemini_embed_model,
                    contents=texts[start : start + _EMBED_BATCH_SIZE],
                    config=types.EmbedContentConfig(
                        output_dimensionality=self._settings.embed_dim,
                        task_type="RETRIEVAL_DOCUMENT",
                    ),
                )
            except Exception as exc:
                raise GeminiUnavailableError(f"Embedding documents failed: {exc}") from exc
            embeddings.extend(list(e.values) for e in response.embeddings)
        return embeddings

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
        self,
        question: str,
        context: str,
        benefits: str,
        cost_note: str | None = None,
        history: Sequence[ChatTurn] = (),
        bill: str | None = None,
    ) -> TextResult:
        prompt = (
            f"Benefits snapshot:\n{benefits}\n\n"
            f"Policy excerpts:\n{context or '(none found)'}\n\n"
            + (f"Latest scanned bill:\n{bill}\n\n" if bill else "")
            + (f"Cost estimate (use these exact figures):\n{cost_note}\n\n" if cost_note else "")
            + f"Member question: {question}"
        )
        contents = [
            types.Content(
                role="user" if turn.role == "user" else "model",
                parts=[types.Part(text=turn.text)],
            )
            for turn in history[-_MAX_HISTORY_TURNS:]
        ]
        contents.append(types.Content(role="user", parts=[types.Part(text=prompt)]))
        text = self._generate(
            contents,
            types.GenerateContentConfig(system_instruction=_CHAT_INSTRUCTION, temperature=0.2),
        )
        if text is None:
            return TextResult(self._fallback_answer(question, context, bill), live=False)
        return TextResult(text, live=True)

    def _fallback_answer(self, question: str, context: str, bill: str | None = None) -> str:
        if bill and mentions_bill(question):
            return f"Here's what I found on your latest bill:\n\n{bill}"
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
        # A scanned PDF's text layer is often just page numbers, so read its pages instead.
        if text.strip() and (not file_bytes or len(text.strip()) >= _MIN_TEXT_LAYER_CHARS):
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
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ValueError("expected a JSON object")
                percent = data.get("coinsurance_percent")
                # Models sometimes answer 0.3 for 30%; real plans never have sub-1% coinsurance.
                if isinstance(percent, int | float) and not isinstance(percent, bool):
                    if 0 < percent < 1:
                        data["coinsurance_percent"] = percent * 100
                points = data.get("summary") or []
                if isinstance(points, list):
                    data["summary"] = "\n".join(f"- {str(p).lstrip('-• ').strip()}" for p in points)
                return PlanResult(data, live=True)
            except ValueError:
                logger.exception("Gemini returned invalid plan JSON; using offline reader")
        if text.strip():
            return PlanResult(extract_plan_numbers_offline(text), live=False)
        return PlanResult({"summary": _UNREADABLE_PHOTO_SUMMARY}, live=False)

    # ------------------------------------------------------------------ #
    # Vision (EOB / bill scanner)
    # ------------------------------------------------------------------ #
    def analyze_eob(
        self, image_bytes: bytes, mime_type: str, policy_context: str, benefits: str = ""
    ) -> EobResult:
        prompt = f"Plan summary to check coverage against:\n{policy_context}"
        if benefits:
            prompt += f"\n\nMember's deductible status before this bill:\n{benefits}"
        text = self._generate(
            [types.Part.from_bytes(data=image_bytes, mime_type=mime_type), prompt],
            types.GenerateContentConfig(
                system_instruction=_EOB_INSTRUCTION,
                temperature=0,
                response_mime_type="application/json",
                response_schema=_EOB_SCHEMA,
            ),
        )
        if text is None:
            return EobResult(self._fallback_eob(), live=False)
        try:
            data = json.loads(text)
            if not isinstance(data, dict):
                raise ValueError("expected a JSON object")
        except ValueError:
            logger.exception("Gemini returned invalid EOB JSON; using sample analysis")
            return EobResult(self._fallback_eob(), live=False)
        return EobResult(data, live=True)

    def _fallback_eob(self) -> dict:
        return {
            "provider": "Mizzou Health Partners (sample)",
            "total_billed": 565.00,
            "line_items": [
                {
                    "code": "99396",
                    "description": "Preventive visit, established, age 40-64",
                    "billed": 250.00,
                    "plan_expected": 0.00,
                    "covered": True,
                    "flag": "Annual wellness visit — preventive care is $0 under your plan.",
                },
                {
                    "code": "90686",
                    "description": "Flu vaccine, preservative free",
                    "billed": 40.00,
                    "plan_expected": 0.00,
                    "covered": True,
                    "flag": "Routine vaccine — covered at 100% under your plan.",
                },
                {
                    "code": "90471",
                    "description": "Vaccine administration",
                    "billed": 25.00,
                    "plan_expected": 0.00,
                    "covered": True,
                    "flag": "Giving the vaccine is part of preventive care — should be $0.",
                },
                {
                    "code": "99396",
                    "description": "Preventive visit (duplicate charge)",
                    "billed": 250.00,
                    "plan_expected": 0.00,
                    "covered": False,
                    "flag": "Exact duplicate of line 1 on the same date.",
                },
            ],
            "overcharge_flags": [
                "Lines 1-3: a wellness visit and flu shot are preventive care, which your "
                "plan covers at 100%.",
                "Line 4: the wellness visit (99396) is billed twice on the same date.",
            ],
            "summary": (
                "Sample analysis: you were billed $565 for a wellness visit and flu shot "
                "that your plan covers in full, including a duplicate visit charge."
            ),
        }


# JSON schema handed to Gemini for structured EOB extraction.
_EOB_SCHEMA = {
    "type": "object",
    "properties": {
        "is_medical_bill": {"type": "boolean"},
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
    "required": ["is_medical_bill", "total_billed", "line_items", "overcharge_flags", "summary"],
}

_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "is_benefits_document": {"type": "boolean"},
        "plan_name": {"type": "string"},
        "deductible": {"type": "number", "nullable": True},
        "coinsurance_percent": {"type": "number", "nullable": True},
        "oop_max": {"type": "number", "nullable": True},
        "summary": {"type": "array", "items": {"type": "string"}},
        "full_text": {"type": "string"},
    },
    "required": [
        "is_benefits_document",
        "deductible",
        "coinsurance_percent",
        "oop_max",
        "summary",
        "full_text",
    ],
}
