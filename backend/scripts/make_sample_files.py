"""Generate the one-click demo files served at ``GET /api/samples/{name}``.

Run from ``backend/`` with ``python -m scripts.make_sample_files``. Each sample
bill matches the saved analysis next to it (``sample-bill.json``,
``surprise-bill.json``) so the demo tells the same story with or without live Gemini.
"""

from __future__ import annotations

from app.routers.samples import SAMPLES_DIR
from tests.pdf_utils import make_text_pdf

SAMPLE_BILL = [
    "MIZZOU HEALTH PARTNERS - PATIENT STATEMENT",
    "Patient: Jordan Tiger          Member ID: ACM-2026-0412",
    "Plan: ACME Corp Health Plan (2026) - PPO, in-network",
    "Date of service: 08/14/2026    Reason: annual preventive wellness exam",
    "",
    "Line  Code   Description                              Billed",
    "1     99396  Preventive visit, established, age 40-64 $250.00",
    "2     90686  Flu vaccine, preservative free           $40.00",
    "3     90471  Vaccine administration                   $25.00",
    "4     99396  Preventive visit, established, age 40-64 $250.00",
    "",
    "Total charges: $565.00",
    "Amount due from patient: $565.00",
]

SURPRISE_BILL = [
    "SHOW-ME ANESTHESIA ASSOCIATES - PATIENT STATEMENT",
    "Patient: Jordan Tiger          Member ID: ACM-2026-0412",
    "Plan: ACME Corp Health Plan (2026) - PPO",
    "Date of service: 09/03/2026    Procedure: outpatient knee arthroscopy",
    "Place of service: Columbia Regional Hospital Surgery Center (in-network with your plan)",
    "Provider network status: OUT-OF-NETWORK anesthesiologist",
    "Scheduled surgery, not an emergency. Patient did not choose the anesthesiologist.",
    "",
    "Line  Code   Description                              Billed",
    "1     01400  Anesthesia for knee joint surgery        $2,100.00",
    "2     64447  Femoral nerve block injection            $600.00",
    "",
    "Total charges: $2,700.00",
    "Insurance payment: $0.00 (provider is out of network)",
    "Amount due from patient: $2,700.00",
]

SAMPLE_BENEFITS = [
    "TIGER HEALTH SILVER PPO - SUMMARY OF BENEFITS AND COVERAGE (2026)",
    "Individual in-network deductible: $3,000 per plan year.",
    "After the deductible you pay 30% coinsurance for most in-network services.",
    "Individual in-network out-of-pocket maximum: $7,500 per plan year.",
    "Preventive care (annual physical, vaccines, screenings) is covered at 100%.",
    "Primary care visit: $35 copay. Specialist visit: $70 copay.",
    "Generic drugs: $15 copay. Preferred brand drugs: $50 copay.",
    "Emergency room: $400 copay, then coinsurance.",
    "Outpatient surgery and imaging require prior authorization.",
]


def main() -> None:
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    (SAMPLES_DIR / "sample-bill.pdf").write_bytes(make_text_pdf(SAMPLE_BILL))
    (SAMPLES_DIR / "surprise-bill.pdf").write_bytes(make_text_pdf(SURPRISE_BILL))
    (SAMPLES_DIR / "sample-benefits.pdf").write_bytes(make_text_pdf(SAMPLE_BENEFITS))
    print(f"Wrote sample files to {SAMPLES_DIR}")


if __name__ == "__main__":
    main()
