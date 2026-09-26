"""Pydantic request/response models shared across routers."""

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    version: str
    gemini_enabled: bool
    supabase_enabled: bool
    vector_store: str
    chat_model: str
    embed_model: str
    indexed_chunks: int


class DocumentIngestRequest(BaseModel):
    title: str = Field(..., description="Human-readable document name.")
    text: str = Field(..., description="Raw policy text to chunk, embed, and index.")


class DocumentIngestResponse(BaseModel):
    title: str
    chunks_indexed: int
    total_chunks: int


class Source(BaseModel):
    document: str
    snippet: str
    score: float


class BenefitsSnapshot(BaseModel):
    deductible_total: float
    deductible_met: float
    deductible_remaining: float
    coinsurance_rate: float
    oop_max: float


class CostEstimate(BaseModel):
    """A back-of-the-envelope out-of-pocket estimate for a billed amount."""

    billed_amount: float
    applied_to_deductible: float
    coinsurance: float
    estimated_out_of_pocket: float
    explanation: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    billed_amount: float | None = Field(
        default=None,
        ge=0,
        description="Optional procedure cost to run an out-of-pocket estimate.",
    )


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
    benefits: BenefitsSnapshot
    cost_estimate: CostEstimate | None = None
    demo_mode: bool


class EobLineItem(BaseModel):
    code: str
    description: str
    billed: float
    plan_expected: float | None = None
    covered: bool
    flag: str | None = Field(
        default=None,
        description="Populated when the line item looks incorrect or overcharged.",
    )


class EobScanResponse(BaseModel):
    provider: str | None = None
    total_billed: float
    line_items: list[EobLineItem]
    overcharge_flags: list[str]
    summary: str
    demo_mode: bool
