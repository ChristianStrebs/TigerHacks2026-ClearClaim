import { useEffect, useState } from "react";
import { getHealth, getPlan } from "./api";
import { ChatPanel } from "./components/ChatPanel";
import { Splash } from "./components/Splash";
import type { HealthResponse, PlanResponse } from "./types";

const MIN_SPLASH_MS = 1400;
const MAX_SPLASH_MS = 5000;

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function orNull<T>(request: Promise<T>): Promise<T | null> {
  try {
    return await Promise.race([request, delay(MAX_SPLASH_MS).then(() => null)]);
  } catch {
    return null;
  }
}

export default function App() {
  const [loaded, setLoaded] = useState(false);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [plan, setPlan] = useState<PlanResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    void Promise.all([orNull(getHealth()), orNull(getPlan()), delay(MIN_SPLASH_MS)]).then(
      ([h, p]) => {
        if (cancelled) return;
        setHealth(h);
        setPlan(p);
        setLoaded(true);
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  if (!loaded) return <Splash />;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo" aria-hidden="true">
            🩺
          </span>
          <div>
            <h1>ClearClaim</h1>
            <p className="tagline">Know what you owe. Catch what you shouldn't.</p>
          </div>
        </div>
        <div className="status">
          {health ? (
            <span
              className={`badge ${health.gemini_enabled ? "live" : "demo"}`}
              title={`Chat model: ${health.chat_model}`}
            >
              {health.gemini_enabled ? "Gemini live" : "Demo mode"}
            </span>
          ) : (
            <span className="badge offline">API offline</span>
          )}
        </div>
      </header>

      <main className="content">
        <ChatPanel initialPlan={plan} />
      </main>

      <footer className="footer">
        No account needed. Financial and administrative guidance only, not medical advice.
      </footer>
    </div>
  );
}
