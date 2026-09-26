"""Sample documents so the demo works without a real bill or benefits PDF."""

from __future__ import annotations

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
            description="Wellness visit bill with $565 the plan should cover. "
            "Upload to POST /api/eob/scan.",
        ),
        SampleFile(
            name="sample-benefits.pdf",
            kind="benefits",
            description="Tiger Health Silver PPO summary of benefits. "
            "Upload to POST /api/plan/upload.",
        ),
    )
}

router = APIRouter(prefix="/api/samples", tags=["samples"])


@router.get("", response_model=list[SampleFile])
def list_samples() -> list[SampleFile]:
    return list(SAMPLES.values())


@router.get("/{name}", response_class=FileResponse)
def get_sample(name: str) -> FileResponse:
    if name not in SAMPLES:
        raise HTTPException(status_code=404, detail="Unknown sample file.")
    return FileResponse(SAMPLES_DIR / name, media_type="application/pdf", filename=name)
