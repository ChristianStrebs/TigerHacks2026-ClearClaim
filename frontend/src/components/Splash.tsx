export function Splash() {
  return (
    <div className="splash" role="status" aria-live="polite">
      <div className="splash-logo" aria-hidden="true">
        🩺
      </div>
      <h1 className="splash-title">ClearClaim</h1>
      <p className="splash-tagline">Know what you owe. Catch what you shouldn't.</p>
      <div className="splash-bar" aria-hidden="true">
        <div className="splash-bar-fill" />
      </div>
      <p className="splash-status">Loading your benefits copilot…</p>
    </div>
  );
}
