import { useEffect, useRef, useState, type ChangeEvent } from "react";
import type { PlanResponse } from "../types";

export type SampleKind = "benefits" | "bill";

interface Props {
  plan: PlanResponse | null;
  busy: boolean;
  onSend: (text: string) => void;
  onBenefitsFile: (file: File) => void;
  onBillFile: (file: File) => void;
  onSample: (kind: SampleKind) => void;
}

const BENEFITS_ACCEPT = "application/pdf,image/png,image/jpeg,image/webp,image/heic,image/heif";
const BILL_ACCEPT = "application/pdf,image/png,image/jpeg,image/webp";

export function Composer({
  plan,
  busy,
  onSend,
  onBenefitsFile,
  onBillFile,
  onSample,
}: Props) {
  const [text, setText] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const benefitsInput = useRef<HTMLInputElement>(null);
  const billInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const onPointerDown = (e: PointerEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenuOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [menuOpen]);

  const pick = (input: HTMLInputElement | null) => {
    setMenuOpen(false);
    input?.click();
  };

  const handleFile =
    (handler: (file: File) => void) => (e: ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      // Reset so choosing the same file again still fires onChange.
      e.target.value = "";
      if (file) handler(file);
    };

  const submit = () => {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    onSend(trimmed);
    setText("");
  };

  const hasOwnPlan = plan?.source === "document";

  return (
    <div className="composer">
      <div className="composer-attachments">
        {hasOwnPlan ? (
          <button
            type="button"
            className="plan-chip filled"
            onClick={() => pick(benefitsInput.current)}
            disabled={busy}
            title="Replace your benefits"
          >
            <span aria-hidden="true">📄</span>
            <span className="plan-chip-label">{plan.plan_name}</span>
            <span className="plan-chip-status">Benefits added ✓</span>
          </button>
        ) : (
          <button
            type="button"
            className="plan-chip empty"
            onClick={() => pick(benefitsInput.current)}
            disabled={busy}
          >
            <span aria-hidden="true">＋</span>
            <span className="plan-chip-label">Add your benefits (PDF or photo)</span>
            <span className="plan-chip-status">Using the sample plan for now</span>
          </button>
        )}
      </div>

      <form
        className="composer-row"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <div className="plus-wrap" ref={menuRef}>
          <button
            type="button"
            className={menuOpen ? "plus-button open" : "plus-button"}
            aria-label="Add a file"
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((open) => !open)}
            disabled={busy}
          >
            +
          </button>
          {menuOpen && (
            <div className="plus-menu" role="menu">
              <button
                type="button"
                role="menuitem"
                className="plus-menu-item"
                onClick={() => pick(benefitsInput.current)}
                autoFocus
              >
                <span className="plus-menu-icon" aria-hidden="true">📄</span>
                <span>
                  <strong>Add my benefits</strong>
                  <small>PDF or photo of your plan</small>
                </span>
              </button>
              <button
                type="button"
                role="menuitem"
                className="plus-menu-item"
                onClick={() => pick(billInput.current)}
              >
                <span className="plus-menu-icon" aria-hidden="true">🧾</span>
                <span>
                  <strong>Scan a bill</strong>
                  <small>Photo or PDF of a bill or EOB</small>
                </span>
              </button>
              <p className="plus-menu-divider">No file handy? Try a sample</p>
              <button
                type="button"
                role="menuitem"
                className="plus-menu-item compact"
                onClick={() => {
                  setMenuOpen(false);
                  onSample("bill");
                }}
              >
                <span className="plus-menu-icon" aria-hidden="true">🧪</span>
                <span>
                  <strong>Sample bill</strong>
                </span>
              </button>
              <button
                type="button"
                role="menuitem"
                className="plus-menu-item compact"
                onClick={() => {
                  setMenuOpen(false);
                  onSample("benefits");
                }}
              >
                <span className="plus-menu-icon" aria-hidden="true">🧪</span>
                <span>
                  <strong>Sample benefits</strong>
                </span>
              </button>
            </div>
          )}
        </div>

        <input
          className="text-input"
          type="text"
          placeholder="Ask about your benefits…"
          aria-label="Ask about your benefits"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <button className="send" type="submit" disabled={busy || !text.trim()}>
          Send
        </button>

        <input
          ref={benefitsInput}
          type="file"
          accept={BENEFITS_ACCEPT}
          hidden
          onChange={handleFile(onBenefitsFile)}
        />
        <input
          ref={billInput}
          type="file"
          accept={BILL_ACCEPT}
          hidden
          onChange={handleFile(onBillFile)}
        />
      </form>
    </div>
  );
}
