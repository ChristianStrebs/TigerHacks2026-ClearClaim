"""Pydantic request/response models shared across routers."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, computed_field

PlanField = Literal["deductible_total", "coinsurance_rate", "oop_max"]


class HealthResponse(BaseModel):
    status: str
    version: str
    gemini_enabled: bool
    supabase_enabled: bool
    vector_store: str
    chat_model: str
    embed_model: str
    indexed_chunks: int
    benefits: BenefitsSnapshot | None = Field(
        description="Null until the member picks the sample plan or submits their own."
    )


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
    demo_fields: list[PlanField] = Field(
        default_factory=list,
        description="Numbers still using demo values because they weren't found in a plan.",
    )


class PlanTextRequest(BaseModel):
    title: str = Field(default="Pasted policy", min_length=1)
    text: str = Field(..., min_length=1, description="Raw policy text to read and index.")


class PlanResponse(BaseModel):
    plan_name: str | None = Field(description="Null when no plan has been chosen yet.")
    source: Literal["none", "demo", "document"] = Field(
        description="none = nothing chosen yet, demo = sample plan, document = member's own plan."
    )
    benefits: BenefitsSnapshot | None
    summary: str
    demo_mode: bool = Field(description="True when the summary did not come from live Gemini.")


class CostEstimate(BaseModel):
    """A back-of-the-envelope out-of-pocket estimate for a billed amount."""

    billed_amount: float
    applied_to_deductible: float
    coinsurance: float
    estimated_out_of_pocket: float
    explanation: str


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(..., min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    history: list[ChatTurn] = Field(
        default_factory=list,
        max_length=20,
        description="Earlier messages in this conversation, oldest first, so follow-ups work.",
    )
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
    bill_scan_id: str | None = Field(
        default=None, description="The saved bill scan the answer could draw on, if any."
    )
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
    scan_id: str = Field(description="Use with GET /api/eob/scans/{scan_id}.")
    file_name: str
    scanned_at: datetime
    plan_name: str = Field(description="The plan this bill was checked against.")
    provider: str | None = None
    total_billed: float
    line_items: list[EobLineItem]
    overcharge_flags: list[str]
    potential_savings: float = Field(
        default=0.0,
        description="Sum of flagged charges the member may not owe (billed minus expected).",
    )
    summary: str
    demo_mode: bool


class SampleFile(BaseModel):
    name: str
    kind: Literal["bill", "benefits"]
    description: str

    @computed_field
    @property
    def url(self) -> str:
        return f"/api/samples/{self.name}"
