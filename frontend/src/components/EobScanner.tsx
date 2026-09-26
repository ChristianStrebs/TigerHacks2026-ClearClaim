import { useState } from "react";
import { scanEob } from "../api";
import type { EobScanResponse } from "../types";

function currency(n: number): string {
  return n.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

export function EobScanner() {
  const [result, setResult] = useState<EobScanResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);

  async function onFile(file: File) {
    setError(null);
    setFileName(file.name);
    setLoading(true);
    try {
      setResult(await scanEob(file));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Scan failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="eob-layout">
      <div className="eob-intro">
        <h2>Bill &amp; EOB scanner</h2>
        <p>
          Upload a photo of a medical bill or Explanation of Benefits. BeneSense
          reads the line items, checks them against your plan, and flags likely
          overcharges or duplicate charges.
        </p>
        <label className="upload">
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp,application/pdf"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void onFile(f);
            }}
          />
          <span>{fileName ? `Selected: ${fileName}` : "Choose a bill image or PDF"}</span>
        </label>
        <p className="eob-hint">
          No bill handy? In demo mode, upload any image to see a sample analysis.
        </p>
      </div>

      {loading && <div className="bubble assistant loading">Scanning bill…</div>}
      {error && <div className="error-banner">{error}</div>}

      {result && (
        <div className="eob-result">
          <div className="eob-summary-card">
            <div>
              <span className="eob-provider">{result.provider ?? "Your bill"}</span>
              <span className="eob-total">Total billed: {currency(result.total_billed)}</span>
            </div>
            <p>{result.summary}</p>
          </div>

          {result.overcharge_flags.length > 0 && (
            <div className="flags-card">
              <h3>⚠ {result.overcharge_flags.length} things to review</h3>
              <ul>
                {result.overcharge_flags.map((f, i) => (
                  <li key={i}>{f}</li>
                ))}
              </ul>
            </div>
          )}

          <table className="line-items">
            <thead>
              <tr>
                <th>Code</th>
                <th>Description</th>
                <th>Billed</th>
                <th>Expected</th>
                <th>Status</th>
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
                  <td>{currency(item.billed)}</td>
                  <td>
                    {item.plan_expected != null ? currency(item.plan_expected) : "—"}
                  </td>
                  <td>{item.covered ? "Covered" : "Check"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
