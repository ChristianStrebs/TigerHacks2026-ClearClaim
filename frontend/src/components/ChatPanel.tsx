import { useEffect, useRef, useState } from "react";
import { resetPlan, scanEob, sendChat, uploadPlan } from "../api";
import { currency } from "../format";
import type { CostEstimate, EobScanResponse, PlanResponse, Source } from "../types";
import { BillResult } from "./BillResult";
import { Composer, type SampleKind } from "./Composer";
import { Markdown } from "./Markdown";
import { PlanCard } from "./PlanCard";

type Turn =
  | { id: number; kind: "question"; text: string }
  | { id: number; kind: "attachment"; fileName: string; purpose: "benefits" | "bill" }
  | {
      id: number;
      kind: "answer";
      text: string;
      sources: Source[];
      estimate: CostEstimate | null;
      live: boolean;
    }
  | { id: number; kind: "plan"; plan: PlanResponse }
  | { id: number; kind: "bill"; result: EobScanResponse }
  | { id: number; kind: "error"; text: string };

type DistributiveOmit<T, K extends PropertyKey> = T extends unknown ? Omit<T, K> : never;
type NewTurn = DistributiveOmit<Turn, "id">;

const SUGGESTIONS = [
  "What is a deductible?",
  "How much will an $18,000 knee surgery cost me?",
  "Is my annual wellness visit covered?",
  "How does coinsurance work?",
];

const SAMPLE_FILES: Record<SampleKind, string> = {
  bill: "sample-bill.pdf",
  benefits: "sample-benefits.pdf",
};

async function loadSample(kind: SampleKind): Promise<File> {
  const name = SAMPLE_FILES[kind];
  const res = await fetch(`${import.meta.env.VITE_API_BASE_URL ?? ""}/api/samples/${name}`);
  if (!res.ok) throw new Error("Couldn't load the sample file.");
  return new File([await res.blob()], name, { type: "application/pdf" });
}

function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : "Something went wrong. Please try again.";
}

function AiTag({ live }: { live: boolean }) {
  return (
    <span className={live ? "ai-tag live" : "ai-tag offline"}>
      {live ? "Answered by Gemini" : "Offline answer"}
    </span>
  );
}

function renderTurn(turn: Turn) {
  switch (turn.kind) {
    case "question":
      return <div className="bubble user">{turn.text}</div>;
    case "attachment":
      return (
        <div className="bubble user attachment">
          <span aria-hidden="true">{turn.purpose === "benefits" ? "📄" : "🧾"}</span>{" "}
          {turn.fileName}
          <small>{turn.purpose === "benefits" ? "Benefits" : "Bill to scan"}</small>
        </div>
      );
    case "answer":
      return (
        <div className="bubble assistant">
          <Markdown text={turn.text} />
          {turn.estimate && (
            <div className="cost-callout">
              <span className="cost-label">Estimated cost to you</span>
              <span className="cost-amount">
                {currency(turn.estimate.estimated_out_of_pocket)}
              </span>
              <span className="cost-explanation">{turn.estimate.explanation}</span>
            </div>
          )}
          {turn.sources.length > 0 && (
            <details className="sources">
              <summary>Where this comes from in your plan ({turn.sources.length})</summary>
              {turn.sources.map((s, j) => (
                <div key={j} className="source">
                  <span className="source-doc">{s.document}</span>
                  <span className="source-snippet">{s.snippet}</span>
                </div>
              ))}
            </details>
          )}
          <AiTag live={turn.live} />
        </div>
      );
    case "plan":
      return (
        <div className="bubble assistant">
          <p>
            {turn.plan.source === "document" ? "I read " : "You're using "}
            <strong>{turn.plan.plan_name}</strong>. Here's what matters for your wallet:
          </p>
          <Markdown text={turn.plan.summary} />
          {turn.plan.benefits.demo_fields.length > 0 && turn.plan.source === "document" && (
            <p className="demo-footnote">
              Some numbers weren't in your document, so demo numbers are shown and
              marked with *.
            </p>
          )}
          {turn.plan.source === "demo" ? (
            <span className="ai-tag sample">Sample plan</span>
          ) : (
            <AiTag live={!turn.plan.demo_mode} />
          )}
        </div>
      );
    case "bill":
      return (
        <div className="bubble assistant wide">
          <BillResult result={turn.result} />
          <AiTag live={!turn.result.demo_mode} />
        </div>
      );
    case "error":
      return (
        <div className="bubble assistant error" role="alert">
          {turn.text}
        </div>
      );
    default: {
      const unreachable: never = turn;
      return unreachable;
    }
  }
}

interface Props {
  initialPlan: PlanResponse | null;
}

export function ChatPanel({ initialPlan }: Props) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [plan, setPlan] = useState<PlanResponse | null>(initialPlan);
  const [busy, setBusy] = useState<string | null>(null);
  const nextId = useRef(0);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const list = listRef.current;
    const last = list?.lastElementChild;
    if (!list || !last) return;
    // Long replies (bill results) would otherwise open scrolled past their headline.
    const lastTop = last.getBoundingClientRect().top - list.getBoundingClientRect().top;
    list.scrollTo({ top: list.scrollTop + lastTop - 12, behavior: "smooth" });
  }, [turns, busy]);

  const addTurns = (...newTurns: NewTurn[]) =>
    setTurns((prev) => [
      ...prev,
      ...newTurns.map((t) => ({ ...t, id: nextId.current++ }) as Turn),
    ]);

  async function run(status: string, before: NewTurn | null, task: () => Promise<NewTurn>) {
    if (busy) return;
    if (before) addTurns(before);
    setBusy(status);
    try {
      addTurns(await task());
    } catch (e) {
      addTurns({ kind: "error", text: errorMessage(e) });
    } finally {
      setBusy(null);
    }
  }

  const ask = (question: string) =>
    run("Thinking…", { kind: "question", text: question }, async () => {
      const res = await sendChat(question);
      return {
        kind: "answer",
        text: res.answer,
        sources: res.sources,
        estimate: res.cost_estimate,
        live: !res.demo_mode,
      };
    });

  const addBenefits = (file: File) =>
    run(
      "Reading your benefits…",
      { kind: "attachment", fileName: file.name, purpose: "benefits" },
      async () => {
        const next = await uploadPlan(file);
        setPlan(next);
        return { kind: "plan", plan: next };
      },
    );

  const scanBill = (file: File) =>
    run(
      "Scanning your bill…",
      { kind: "attachment", fileName: file.name, purpose: "bill" },
      async () => ({ kind: "bill", result: await scanEob(file) }),
    );

  async function trySample(kind: SampleKind) {
    try {
      const file = await loadSample(kind);
      if (kind === "bill") await scanBill(file);
      else await addBenefits(file);
    } catch (e) {
      addTurns({ kind: "error", text: errorMessage(e) });
    }
  }

  const switchToSamplePlan = () =>
    run("Switching to the sample plan…", null, async () => {
      const next = await resetPlan();
      setPlan(next);
      return { kind: "plan", plan: next };
    });

  return (
    <div className="chat-layout">
      <div className="chat-main">
        <div className="messages" ref={listRef} aria-live="polite">
          {turns.length === 0 && (
            <div className="empty-state">
              <h2>Ask about your benefits</h2>
              <p>
                Submit your benefits with the <strong>+</strong> button to get answers about
                your plan, or ask a general question about employee benefits.
              </p>
              <div className="suggestions">
                {SUGGESTIONS.map((s) => (
                  <button key={s} className="chip" onClick={() => void ask(s)}>
                    {s}
                  </button>
                ))}
              </div>
              <div className="suggestions">
                <button className="chip sample" onClick={() => void trySample("bill")}>
                  🧾 Scan a sample bill
                </button>
              </div>
            </div>
          )}
          {turns.map((turn) => (
            <div key={turn.id} className="turn">
              {renderTurn(turn)}
            </div>
          ))}
          {busy && <div className="bubble assistant loading">{busy}</div>}
        </div>

        <Composer
          plan={plan}
          busy={busy !== null}
          onSend={(text) => void ask(text)}
          onBenefitsFile={(file) => void addBenefits(file)}
          onBillFile={(file) => void scanBill(file)}
          onSample={(kind) => void trySample(kind)}
        />
      </div>

      <aside className="chat-side">
        {plan ? (
          <PlanCard plan={plan} onUseSample={() => void switchToSamplePlan()} busy={busy !== null} />
        ) : (
          <div className="benefits-card muted">
            Couldn't load your plan. Check that the ClearClaim API is running, then refresh.
          </div>
        )}
      </aside>
    </div>
  );
}
