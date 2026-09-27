"""Sample documents so the demo works without a real bill or benefits PDF."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.schemas import SampleFile

SAMPLES_DIR = Path(__file__).resolve().parents[1] / "data" / "samples"

SAMPLES: dict[str, SampleFile] = {
    sample.name: sample
    for sample in (
        SampleFile(
            name="sample-bill.pdf",
            kind="bill",
            label="Wellness visit bill",
            description="Wellness visit bill with $565 the plan should cover. "
            "Upload to POST /api/eob/scan.",
        ),
        SampleFile(
            name="surprise-bill.pdf",
            kind="bill",
            label="Surprise anesthesia bill",
            description="Out-of-network anesthesiologist at an in-network surgery center: "
            "a surprise bill the No Surprises Act protects. Upload to POST /api/eob/scan.",
        ),
        SampleFile(
            name="sample-benefits.pdf",
            kind="benefits",
            label="Tiger Health Silver PPO",
            description="Tiger Health Silver PPO summary of benefits. "
            "Upload to POST /api/plan/upload.",
        ),
    )
}


@lru_cache(maxsize=1)
def _sample_bills_by_digest() -> dict[str, str]:
    return {
        hashlib.sha256((SAMPLES_DIR / name).read_bytes()).hexdigest(): name
        for name, sample in SAMPLES.items()
        if sample.kind == "bill"
    }


def offline_bill_analysis(digest: str) -> dict | None:
    """The saved analysis of a sample bill, so the demo works without live AI.

    Each sample bill's analysis sits next to it as ``<name>.json``. Any other file
    gets None: a saved analysis must never be passed off as a member's own bill.
    """
    name = _sample_bills_by_digest().get(digest)
    if name is None:
        return None
    return json.loads((SAMPLES_DIR / name).with_suffix(".json").read_text("utf-8"))


router = APIRouter(prefix="/api/samples", tags=["samples"])


@router.get("", response_model=list[SampleFile])
def list_samples() -> list[SampleFile]:
    return list(SAMPLES.values())


@router.get("/{name}", response_class=FileResponse)
def get_sample(name: str) -> FileResponse:
    if name not in SAMPLES:
        raise HTTPException(status_code=404, detail="Unknown sample file.")
    return FileResponse(SAMPLES_DIR / name, media_type="application/pdf", filename=name)
