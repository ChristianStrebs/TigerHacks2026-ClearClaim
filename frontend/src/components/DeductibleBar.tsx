import type { BenefitsSnapshot } from "../types";

interface Props {
  benefits: BenefitsSnapshot;
}

function currency(n: number): string {
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

export function DeductibleBar({ benefits }: Props) {
  const pct = Math.min(
    100,
    Math.round((benefits.deductible_met / benefits.deductible_total) * 100),
  );

  return (
    <div className="benefits-card">
      <h3>Your plan this year</h3>
      <div className="benefits-row">
        <span>Deductible</span>
        <span>
          {currency(benefits.deductible_met)} / {currency(benefits.deductible_total)}
        </span>
      </div>
      <div className="progress" role="progressbar" aria-valuenow={pct}>
        <div className="progress-fill" style={{ width: `${pct}%` }} />
      </div>
      <p className="benefits-hint">
        {currency(benefits.deductible_remaining)} left before your plan pays{" "}
        {Math.round((1 - benefits.coinsurance_rate) * 100)}%.
      </p>
      <div className="benefits-row muted">
        <span>Coinsurance</span>
        <span>{Math.round(benefits.coinsurance_rate * 100)}%</span>
      </div>
      <div className="benefits-row muted">
        <span>Out-of-pocket max</span>
        <span>{currency(benefits.oop_max)}</span>
      </div>
    </div>
  );
}
