import { Icon } from "../Icon";
import type { BenefitsSnapshot, PlanField } from "../types";

export const money = (value: number) =>
  value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  });
export const demoMark = (benefits: BenefitsSnapshot, field: PlanField) =>
  benefits.demo_fields.includes(field) ? "*" : "";

export function DemoNote({ benefits }: { benefits: BenefitsSnapshot }) {
  if (!benefits.demo_fields.length) return null;
  return (
    <p className="demo-note">
      <span className="demo-badge">Demo*</span> Starred figures use sample
      values that were not extracted from your plan.
    </p>
  );
}

export function CoverageCard({
  benefits,
  loading,
  onOpen,
  action = "View plan details",
}: {
  benefits: BenefitsSnapshot | null;
  loading: boolean;
  onOpen: () => void;
  action?: string;
}) {
  const percent =
    benefits && benefits.deductible_total > 0
      ? Math.min(
          100,
          Math.max(
            0,
            (benefits.deductible_met / benefits.deductible_total) * 100,
          ),
        )
      : 0;
  return (
    <section className="benefit-card">
      <div className="card-top">
        <span>
          <Icon name="shield" size={17} /> YOUR COVERAGE
        </span>
        <span>ACTIVE PLAN</span>
      </div>
      <h2>
        {benefits ? (
          <>
            {money(benefits.deductible_remaining)}
            {demoMark(benefits, "deductible_total")}
          </>
        ) : loading ? (
          "Loading…"
        ) : (
          "Not connected"
        )}
        <span>
          {benefits
            ? "deductible remaining"
            : "Your benefits come from the backend."}
        </span>
      </h2>
      {benefits && (
        <>
          <div
            className="meter"
            role="progressbar"
            aria-label="Deductible met"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent}
          >
            <i style={{ width: `${percent}%` }} />
          </div>
          <div className="meter-label">
            <span>{money(benefits.deductible_met)} met</span>
            <span>
              of {money(benefits.deductible_total)}
              {demoMark(benefits, "deductible_total")}
            </span>
          </div>
        </>
      )}
      <button className="card-link" onClick={onOpen}>
        {action}
        <Icon name="arrow" size={18} />
      </button>
    </section>
  );
}
