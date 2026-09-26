import { currency, percent } from "../format";
import type { PlanField, PlanResponse } from "../types";
import { Markdown } from "./Markdown";

interface Props {
  plan: PlanResponse;
  onUseSample: () => void;
  busy: boolean;
}

export function PlanCard({ plan, onUseSample, busy }: Props) {
  const { benefits } = plan;
  const isDemo = (field: PlanField) => benefits.demo_fields.includes(field);
  const mark = (field: PlanField) => (isDemo(field) ? "*" : "");
  const hasDemoNumbers = benefits.demo_fields.length > 0;
  const pct =
    benefits.deductible_total > 0
      ? Math.min(100, Math.round((benefits.deductible_met / benefits.deductible_total) * 100))
      : 100;

  return (
    <div className="plan-card-wrap">
      {hasDemoNumbers && (
        <div className="demo-pill" role="note">
          Demo*
        </div>
      )}
      <div className="benefits-card">
        <p className="plan-eyebrow">Your plan this year</p>
        <h3 className="plan-name">{plan.plan_name}</h3>

        <div className="benefits-row">
          <span>Deductible{mark("deductible_total")}</span>
          <span>
            {currency(benefits.deductible_met)} / {currency(benefits.deductible_total)}
          </span>
        </div>
        <div
          className="progress"
          role="progressbar"
          aria-label="Deductible paid so far"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={pct}
        >
          <div className="progress-fill" style={{ width: `${pct}%` }} />
        </div>
        <p className="benefits-hint">
          <strong>{currency(benefits.deductible_remaining)}</strong> left before your plan
          pays {percent(1 - benefits.coinsurance_rate)} of most bills.
        </p>

        <div className="benefits-row muted">
          <span>You pay after deductible{mark("coinsurance_rate")}</span>
          <span>{percent(benefits.coinsurance_rate)}</span>
        </div>
        <div className="benefits-row muted">
          <span>Most you'll pay this year{mark("oop_max")}</span>
          <span>{currency(benefits.oop_max)}</span>
        </div>

        {hasDemoNumbers && (
          <p className="demo-footnote">
            {plan.source === "demo"
              ? "*Demo numbers. Tap + to submit your benefits and see yours."
              : "*Not found in your document, so a demo number is shown."}
          </p>
        )}

        {plan.summary && (
          <details className="plan-summary">
            <summary>Plan summary</summary>
            <Markdown text={plan.summary} />
          </details>
        )}

        {plan.source === "document" && (
          <button className="link-button" onClick={onUseSample} disabled={busy}>
            Switch back to the sample plan
          </button>
        )}
      </div>
    </div>
  );
}
