import { useEffect, useState } from "react";
import { getHealth } from "./api";
import { ChatPanel } from "./components/ChatPanel";
import { EobScanner } from "./components/EobScanner";
import type { BenefitsSnapshot, HealthResponse } from "./types";

type Tab = "chat" | "eob";

export default function App() {
  const [tab, setTab] = useState<Tab>("chat");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [, setBenefits] = useState<BenefitsSnapshot | null>(null);

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo">🩺</span>
          <div>
            <h1>BeneSense</h1>
            <p className="tagline">Your healthcare benefits copilot</p>
          </div>
        </div>
        <div className="status">
          {health ? (
            <>
              <span
                className={`badge ${health.gemini_enabled ? "live" : "demo"}`}
                title={`Chat model: ${health.chat_model}`}
              >
                {health.gemini_enabled ? "Gemini live" : "Demo mode"}
              </span>
              <span className="badge subtle">{health.indexed_chunks} policy chunks</span>
            </>
          ) : (
            <span className="badge offline">API offline</span>
          )}
        </div>
      </header>

      <nav className="tabs">
        <button
          className={tab === "chat" ? "tab active" : "tab"}
          onClick={() => setTab("chat")}
        >
          Benefits chat
        </button>
        <button
          className={tab === "eob" ? "tab active" : "tab"}
          onClick={() => setTab("eob")}
        >
          Bill scanner
        </button>
      </nav>

      <main className="content">
        {tab === "chat" ? (
          <ChatPanel onBenefits={setBenefits} />
        ) : (
          <EobScanner />
        )}
      </main>

      <footer className="footer">
        BeneSense focuses on administrative &amp; financial guidance — not clinical
        advice. {health && `Chat: ${health.chat_model} · Embeddings: ${health.embed_model}`}
      </footer>
    </div>
  );
}
