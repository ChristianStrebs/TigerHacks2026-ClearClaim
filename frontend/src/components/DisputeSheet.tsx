import { useEffect, useRef, useState } from "react";
import { getDisputeKit } from "../api";
import { Icon } from "../Icon";
import type { DisputeKit, EobScanResponse } from "../types";

type KitTab = "letter" | "call";

const KIT_FILES: Record<KitTab, string> = {
  letter: "clearclaim-dispute-letter.txt",
  call: "clearclaim-call-script.txt",
};

function kitText(kit: DisputeKit, tab: KitTab): string {
  switch (tab) {
    case "letter":
      return kit.letter;
    case "call":
      return kit.call_script
        .map((line, index) => `${index + 1}. ${line}`)
        .join("\n");
    default: {
      const unhandled: never = tab;
      return unhandled;
    }
  }
}

const errorMessage = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "Something went wrong. Please try again.";

export function DisputeSheet({
  scan,
  onClose,
}: {
  scan: EobScanResponse;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  // StrictMode runs effects twice in development; each kit costs an AI request.
  const requested = useRef(-1);
  const [attempt, setAttempt] = useState(0);
  const [kit, setKit] = useState<DisputeKit | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<KitTab>("letter");
  const [done, setDone] = useState<ReadonlySet<number>>(new Set());
  const [copied, setCopied] = useState(false);
  const provider = scan.provider ?? "your provider";

  useEffect(() => {
    if (!dialog.current?.open) dialog.current?.showModal();
  }, []);
  useEffect(() => {
    if (requested.current === attempt) return;
    requested.current = attempt;
    getDisputeKit(scan.scan_id)
      .then(setKit)
      .catch((reason: unknown) => setError(errorMessage(reason)));
  }, [attempt, scan.scan_id]);

  function retry() {
    setError("");
    setAttempt((old) => old + 1);
  }
  async function copy(current: DisputeKit) {
    try {
      await navigator.clipboard.writeText(kitText(current, tab));
      setError("");
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Couldn't copy. Select the text and copy it instead.");
    }
  }
  function download(current: DisputeKit) {
    const url = URL.createObjectURL(
      new Blob([kitText(current, tab)], { type: "text/plain" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = KIT_FILES[tab];
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function toggle(step: number) {
    setDone((old) => {
      const next = new Set(old);
      if (next.has(step)) next.delete(step);
      else next.add(step);
      return next;
    });
  }

  return (
    <dialog
      ref={dialog}
      className="policy-dialog dispute-dialog"
      aria-labelledby="dispute-title"
      onClose={onClose}
    >
      <div className="section-heading">
        <h2 id="dispute-title">Fix this bill</h2>
        <button
          type="button"
          className="icon-button"
          aria-label="Close"
          onClick={() => dialog.current?.close()}
        >
          <Icon name="close" />
        </button>
      </div>
      <p className="shared-warning">
        A letter and call script for your bill from {provider}. Fill in the
        [bracketed] parts before you send it.
      </p>
      {!kit && !error && (
        <p className="notice" role="status">
          Writing your letter… AI requests may take a minute.
        </p>
      )}
      {!kit && error && (
        <>
          <p className="error" role="alert">
            {error}
          </p>
          <button className="primary full sample-button" onClick={retry}>
            Try again
          </button>
        </>
      )}
      {kit && (
        <>
          <div className="dispute-tabs">
            <div className="upload-tabs" role="group" aria-label="Dispute kit">
              <button
                aria-pressed={tab === "letter"}
                onClick={() => setTab("letter")}
              >
                Letter
              </button>
              <button
                aria-pressed={tab === "call"}
                onClick={() => setTab("call")}
              >
                Call script
              </button>
            </div>
            <span className="mode">
              {kit.demo_mode ? "Template" : "Written by Gemini"}
            </span>
          </div>
          {tab === "letter" ? (
            <pre className="dispute-text" tabIndex={0}>
              {kit.letter}
            </pre>
          ) : (
            <ol className="dispute-text call-script" tabIndex={0}>
              {kit.call_script.map((line, index) => (
                <li key={index}>{line}</li>
              ))}
            </ol>
          )}
          <div className="dispute-actions">
            <button className="primary" onClick={() => void copy(kit)}>
              <Icon name={copied ? "check" : "plan"} size={16} />
              {copied ? "Copied" : "Copy"}
            </button>
            <button className="secondary" onClick={() => download(kit)}>
              Download .txt
            </button>
            {tab === "letter" && (
              <a
                className="secondary"
                href={`mailto:?subject=${encodeURIComponent(
                  `Request to review my bill from ${provider}`,
                )}&body=${encodeURIComponent(kit.letter)}`}
              >
                Email
              </a>
            )}
          </div>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <p className="notice">{kit.deadline_note}</p>
          <div className="dispute-checklist-head">
            <strong>Checklist</strong>
            <small>
              {done.size} of {kit.checklist.length} done
            </small>
          </div>
          <ul className="dispute-checklist">
            {kit.checklist.map((step, index) => (
              <li key={index}>
                <label>
                  <input
                    type="checkbox"
                    checked={done.has(index)}
                    onChange={() => toggle(index)}
                  />
                  <span>{step}</span>
                </label>
              </li>
            ))}
          </ul>
          <p className="rights-note">
            General information, not legal advice. Read the letter and check
            every detail before you send it.
          </p>
        </>
      )}
    </dialog>
  );
}
