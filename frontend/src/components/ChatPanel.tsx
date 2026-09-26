import { useRef, useState } from "react";
import { sendChat } from "../api";
import type { BenefitsSnapshot, ChatResponse, Source } from "../types";
import { DeductibleBar } from "./DeductibleBar";

interface ChatTurn {
  role: "user" | "assistant";
  text: string;
  sources?: Source[];
  costExplanation?: string;
}

const SUGGESTIONS = [
  "What is my deductible and how much is left?",
  "How much will a knee surgery cost me?",
  "Is my annual wellness visit covered?",
  "What do I pay for generic prescriptions?",
];

interface Props {
  onBenefits: (b: BenefitsSnapshot) => void;
}

export function ChatPanel({ onBenefits }: Props) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [billed, setBilled] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [benefits, setBenefits] = useState<BenefitsSnapshot | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  async function ask(question: string) {
    const trimmed = question.trim();
    if (!trimmed || loading) return;
    setError(null);
    setInput("");
    // Capture the procedure cost for this question, then clear it so an
    // unrelated follow-up question doesn't reuse a stale estimate.
    const billedAmount = billed ? Number(billed) : undefined;
    setBilled("");
    setTurns((prev) => [...prev, { role: "user", text: trimmed }]);
    setLoading(true);
    try {
      const res: ChatResponse = await sendChat(trimmed, billedAmount);
      setBenefits(res.benefits);
      onBenefits(res.benefits);
      setTurns((prev) => [
        ...prev,
        {
          role: "assistant",
          text: res.answer,
          sources: res.sources,
          costExplanation: res.cost_estimate?.explanation,
        },
      ]);
      requestAnimationFrame(() => {
        listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="chat-layout">
      <div className="chat-main">
        <div className="messages" ref={listRef}>
          {turns.length === 0 && (
            <div className="empty-state">
              <h2>Ask about your benefits</h2>
              <p>
                BeneSense reads your plan documents and answers in plain English —
                with the exact dollars based on your deductible.
              </p>
              <div className="suggestions">
                {SUGGESTIONS.map((s) => (
                  <button key={s} className="chip" onClick={() => ask(s)}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
          {turns.map((turn, i) => (
            <div key={i} className={`bubble ${turn.role}`}>
              <div className="bubble-text">{turn.text}</div>
              {turn.costExplanation && (
                <div className="cost-callout">{turn.costExplanation}</div>
              )}
              {turn.sources && turn.sources.length > 0 && (
                <details className="sources">
                  <summary>{turn.sources.length} policy sources</summary>
                  {turn.sources.map((s, j) => (
                    <div key={j} className="source">
                      <span className="source-doc">{s.document}</span>
                      <span className="source-snippet">{s.snippet}</span>
                    </div>
                  ))}
                </details>
              )}
            </div>
          ))}
          {loading && <div className="bubble assistant loading">Thinking…</div>}
        </div>

        {error && <div className="error-banner">{error}</div>}

        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault();
            void ask(input);
          }}
        >
          <input
            className="cost-input"
            type="number"
            min="0"
            placeholder="Procedure $ (optional)"
            value={billed}
            onChange={(e) => setBilled(e.target.value)}
            aria-label="Optional procedure cost"
          />
          <input
            className="text-input"
            type="text"
            placeholder="Ask about your coverage…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
          />
          <button className="send" type="submit" disabled={loading}>
            Send
          </button>
        </form>
      </div>

      <aside className="chat-side">
        {benefits && <DeductibleBar benefits={benefits} />}
        {!benefits && (
          <div className="benefits-card muted">
            Ask a question to load your benefits snapshot.
          </div>
        )}
      </aside>
    </div>
  );
}
