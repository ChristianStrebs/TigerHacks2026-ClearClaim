import { currency } from "../format";
import type { EobScanResponse } from "../types";

export function BillResult({ result }: { result: EobScanResponse }) {
  const hasSavings = result.potential_savings > 0;

  return (
    <div className="bill-result">
      <div className={hasSavings ? "money-at-risk" : "money-at-risk clear"}>
        <span className="money-at-risk-label">
          {hasSavings ? "Money at risk" : "No problems found"}
        </span>
        <span className="money-at-risk-amount">{currency(result.potential_savings, true)}</span>
        <span className="money-at-risk-note">
          {hasSavings
            ? "This is money you may not owe. Ask the billing office before you pay."
            : "Every charge on this bill looks consistent with your plan."}
        </span>
      </div>

      <div className="bill-meta">
        <span className="bill-provider">{result.provider ?? "Your bill"}</span>
        <span>Total billed: {currency(result.total_billed, true)}</span>
      </div>
      {result.summary && <p className="bill-summary">{result.summary}</p>}

      {result.overcharge_flags.length > 0 && (
        <div className="flags-card">
          <h4>
            <span aria-hidden="true">⚠ </span>
            {result.overcharge_flags.length} things to review
          </h4>
          <ul>
            {result.overcharge_flags.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="table-scroll">
        <table className="line-items">
          <thead>
            <tr>
              <th scope="col">Code</th>
              <th scope="col">Description</th>
              <th scope="col">Billed</th>
              <th scope="col">You should owe</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {result.line_items.map((item, i) => (
              <tr key={i} className={item.flag ? "flagged" : ""}>
                <td>{item.code}</td>
                <td>
                  {item.description}
                  {item.flag && <div className="line-flag">{item.flag}</div>}
                </td>
                <td>{currency(item.billed, true)}</td>
                <td>
                  {item.plan_expected != null ? currency(item.plan_expected, true) : "—"}
                </td>
                <td>{item.flag ? "Review" : item.covered ? "Covered" : "Check"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
