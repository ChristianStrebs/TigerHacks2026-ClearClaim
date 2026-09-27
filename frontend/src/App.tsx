import { useEffect, useRef, useState } from "react";
import {
  ApiError,
  chooseSamplePlan,
  clearPlan,
  deleteScan,
  downloadSample,
  getChatHistory,
  getHealth,
  getPlan,
  getSamples,
  getScans,
  scanEob,
  sendChat,
  submitPlanText,
  uploadPlan,
  UPLOAD_ACCEPT,
} from "./api";
import { Icon } from "./Icon";
import { chatHistory } from "./chatHistory";
import { ChoosePlan } from "./components/ChoosePlan";
import {
  CoverageCard,
  DemoNote,
  deductiblePercent,
  demoMark,
  money,
} from "./components/CoverageCard";
import { PolicyText } from "./components/PolicyText";
import type {
  BenefitsSnapshot,
  ChatResponse,
  EobScanResponse,
  HealthResponse,
  PlanResponse,
  PlanSource,
  SampleFile,
} from "./types";

type Tab = "home" | "chat" | "scan" | "plan";
type Pending = "chat" | "scan" | "remove" | "plan" | null;
type Sheet = "upload" | "clear" | "remove" | null;
type PlanAction = "upload" | "text" | "sample-file" | "sample-plan" | "clear";
interface Turn {
  question: string;
  response?: ChatResponse;
  error?: string;
}

const SUGGESTIONS = [
  "What is my deductible and how much is left?",
  "How much will an $18,000 knee surgery cost me?",
  "Is my annual wellness visit covered?",
  "What do I pay for generic prescriptions?",
];
// Matches MAX_SAVED_SCANS in backend/app/services/storage.py.
const MAX_LISTED_BILLS = 5;
const BILL_SUGGESTIONS = [
  "Which charges on my bill should I question?",
  "Why was I charged twice?",
  "Explain my bill in plain English.",
  "What should I say when I call the billing office?",
];
function planNotice(source: PlanSource): string {
  switch (source) {
    case "none":
      return "Started over. Choose sample data or add your own plan.";
    case "demo":
      return "Sample data loaded. Figures marked Demo* are made up.";
    case "document":
      return "Active plan updated. Chat and bill scans now use this plan.";
    default: {
      const unhandled: never = source;
      return unhandled;
    }
  }
}
function pendingStatus(kind: Exclude<Pending, null>): string {
  switch (kind) {
    case "chat":
      return "Checking your plan… AI requests may take a minute or more.";
    case "scan":
      return "Reviewing the bill… AI requests may take a minute or more.";
    case "remove":
      return "Removing the bill…";
    case "plan":
      return "Updating your plan… AI requests may take a minute or more.";
    default: {
      const unhandled: never = kind;
      return unhandled;
    }
  }
}
function sheetTitle(sheet: Sheet): string {
  switch (sheet) {
    case "clear":
      return "Start over?";
    case "remove":
      return "Remove this bill?";
    case "upload":
    case null:
      return "Add your plan";
    default: {
      const unhandled: never = sheet;
      return unhandled;
    }
  }
}
// Scanned bills move deductible progress; only a different plan should count as a change.
const planIdentity = (plan: PlanResponse) =>
  JSON.stringify({
    ...plan,
    benefits: plan.benefits && {
      ...plan.benefits,
      deductible_met: 0,
      deductible_remaining: 0,
    },
  });
const shortDate = (iso: string) =>
  new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
const errorMessage = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "Something went wrong. Please try again.";
const aiLabel = (demo: boolean) =>
  demo ? "Offline answer" : "Answered by Gemini";

export default function App() {
  const [tab, setTab] = useState<Tab>("home");
  const [splash, setSplash] = useState(true);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [benefits, setBenefits] = useState<BenefitsSnapshot | null>(null);
  const [samples, setSamples] = useState<SampleFile[]>([]);
  const [syncing, setSyncing] = useState(true);
  const [connectionError, setConnectionError] = useState("");
  const [sampleError, setSampleError] = useState("");
  const [pending, setPending] = useState<Pending>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [scans, setScans] = useState<EobScanResponse[]>([]);
  const [review, setReview] = useState<EobScanResponse | null>(null);
  const [scanError, setScanError] = useState("");
  const [sheet, setSheet] = useState<Sheet>(null);
  const [title, setTitle] = useState("");
  const [policyText, setPolicyText] = useState("");
  const [planError, setPlanError] = useState("");
  const [notice, setNotice] = useState("");
  const [attachedFile, setAttachedFile] = useState<File | null>(null);
  const [uploadKind, setUploadKind] = useState<"file" | "text">("file");
  const [sampleName, setSampleName] = useState("");
  const scroll = useRef<HTMLDivElement>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  // Also prevents rapid double clicks before React paints disabled controls.
  const operation = useRef(false);
  const syncVersion = useRef(0);
  const planSignature = useRef("");
  const busy = pending !== null || syncing;
  const hasPlan = !!plan && plan.source !== "none";
  const canChoosePlan = !!health && !busy;
  const available = hasPlan && canChoosePlan;
  const privateData = health?.supabase_enabled ?? false;

  async function refresh() {
    if (operation.current) return;
    const version = ++syncVersion.current;
    setSyncing(true);
    setConnectionError("");
    const [h, p, s, saved, history] = await Promise.allSettled([
      getHealth(),
      getPlan(),
      getSamples(),
      getScans(),
      getChatHistory(),
    ]);
    if (version !== syncVersion.current) return;
    const errors: string[] = [];
    if (h.status === "fulfilled") {
      setHealth(h.value);
    } else {
      setHealth(null);
      errors.push(errorMessage(h.reason));
    }
    if (p.status === "fulfilled") {
      const signature = planIdentity(p.value);
      if (planSignature.current && signature !== planSignature.current) {
        setTurns([]);
        setScans([]);
        setReview(null);
        setNotice(
          "Your plan was changed in another tab. Previous results have been cleared.",
        );
      }
      planSignature.current = signature;
      setPlan(p.value);
      setBenefits(p.value.benefits);
    } else {
      setPlan(null);
      errors.push(
        p.reason instanceof ApiError && p.reason.status === 404
          ? "The running backend has no active-plan API. Use the updated backend branch (f2c4a72 or compatible)."
          : errorMessage(p.reason),
      );
    }
    if (s.status === "fulfilled") {
      setSamples(s.value);
      setSampleError("");
    } else {
      setSamples([]);
      setSampleError(
        "Sample files are unavailable. You can still upload your own file.",
      );
    }
    // The backend drops scans and chats when the plan changes, so what it returns is current.
    if (saved.status === "fulfilled") {
      setScans(saved.value);
      setReview(saved.value[0] ?? null);
    }
    if (history.status === "fulfilled")
      setTurns(
        history.value.map(({ question, response }) => ({ question, response })),
      );
    setConnectionError([...new Set(errors)].join(" "));
    setSyncing(false);
  }

  useEffect(() => {
    void refresh();
    return () => {
      syncVersion.current += 1;
    };
  }, []);
  useEffect(() => {
    if (!splash) return;
    const timer = setTimeout(() => setSplash(false), 2300);
    return () => clearTimeout(timer);
  }, [splash]);
  useEffect(() => {
    scroll.current?.scrollTo({ top: 0, behavior: "instant" });
  }, [tab]);
  useEffect(() => {
    if (tab === "chat")
      scroll.current?.scrollTo({
        top: scroll.current.scrollHeight,
        behavior: "smooth",
      });
  }, [turns, pending, tab]);
  useEffect(() => {
    if (sheet) dialog.current?.showModal();
    else dialog.current?.close();
  }, [sheet]);

  function begin(kind: Exclude<Pending, null>) {
    if (operation.current || syncing) return false;
    operation.current = true;
    syncVersion.current += 1;
    setPending(kind);
    return true;
  }
  function finish() {
    operation.current = false;
    setPending(null);
  }
  function openUpload() {
    setPlanError("");
    setNotice("");
    setAttachedFile(null);
    setSampleName("");
    setSheet("upload");
  }
  function acceptPlan(next: PlanResponse, nextTab: Tab) {
    planSignature.current = planIdentity(next);
    setPlan(next);
    setBenefits(next.benefits);
    // Results from the previous plan must not appear to describe the replacement.
    setTurns([]);
    setScans([]);
    setReview(null);
    setScanError("");
    setTitle("");
    setPolicyText("");
    setAttachedFile(null);
    setSampleName("");
    setConnectionError("");
    setSheet(null);
    setTab(nextTab);
    setNotice(planNotice(next.source));
  }
  async function requestPlan(action: PlanAction): Promise<PlanResponse> {
    switch (action) {
      case "sample-plan":
        return chooseSamplePlan();
      case "clear":
        return clearPlan();
      case "text":
        return submitPlanText(
          title.trim() || "Pasted policy",
          policyText.trim(),
        );
      case "sample-file": {
        const selected = samples.find(
          (sample) => sample.name === sampleName && sample.kind === "benefits",
        );
        if (!selected) throw new Error("Choose a sample benefits file.");
        return uploadPlan(await downloadSample(selected));
      }
      case "upload":
        if (!attachedFile) throw new Error("Choose a plan file first.");
        return uploadPlan(attachedFile);
      default: {
        const unhandled: never = action;
        return unhandled;
      }
    }
  }
  async function changePlan(action: PlanAction) {
    if (!begin("plan")) return;
    setPlanError("");
    setNotice("");
    try {
      const next = await requestPlan(action);
      // The sample and start-over paths begin from Home; plan uploads show the summary.
      acceptPlan(
        next,
        action === "sample-plan" || action === "clear" ? "home" : "plan",
      );
    } catch (error) {
      setPlanError(errorMessage(error));
    } finally {
      finish();
    }
  }
  async function ask(message: string) {
    const trimmed = message.trim();
    if (!trimmed || !available || !begin("chat")) return;
    setQuestion("");
    setTab("chat");
    setTurns((old) => [...old, { question: trimmed }]);
    try {
      const response = await sendChat(trimmed, chatHistory(turns));
      setBenefits(response.benefits);
      setTurns((old) =>
        old.map((turn, index) =>
          index === old.length - 1 ? { ...turn, response } : turn,
        ),
      );
    } catch (error) {
      setTurns((old) =>
        old.map((turn, index) =>
          index === old.length - 1
            ? { ...turn, error: errorMessage(error) }
            : turn,
        ),
      );
      setQuestion(trimmed);
    } finally {
      finish();
    }
  }
  async function reloadBenefits() {
    try {
      const next = await getPlan();
      planSignature.current = planIdentity(next);
      setPlan(next);
      setBenefits(next.benefits);
    } catch {
      // The coverage card catches up on the next refresh.
    }
  }
  async function scanBill(file?: File, sample?: SampleFile) {
    if (!available || !begin("scan")) return;
    // A rejected file doesn't replace the saved review the chat still uses.
    const previous = review;
    setScanError("");
    setNotice("");
    setReview(null);
    try {
      const selected = file ?? (sample ? await downloadSample(sample) : null);
      if (!selected) throw new Error("Choose a bill to review.");
      const scan = await scanEob(selected);
      // The backend replaces an earlier scan of the same file.
      setScans((old) =>
        [
          scan,
          ...old.filter(
            (s) =>
              s.scan_id !== scan.scan_id &&
              (!scan.file_sha256 || s.file_sha256 !== scan.file_sha256),
          ),
        ].slice(0, MAX_LISTED_BILLS),
      );
      setReview(scan);
      if (scan.applied_to_deductible > 0)
        setNotice(
          `Your bill added ${money(scan.applied_to_deductible)} to your deductible.`,
        );
      await reloadBenefits();
    } catch (error) {
      setReview(previous);
      setScanError(errorMessage(error));
    } finally {
      finish();
    }
  }
  async function removeBill() {
    if (!review || !begin("remove")) return;
    setScanError("");
    setNotice("");
    try {
      await deleteScan(review.scan_id).catch((error: unknown) => {
        if (!(error instanceof ApiError && error.status === 404)) throw error;
      });
      const rest = await getScans();
      setScans(rest);
      setReview(rest[0] ?? null);
      setSheet(null);
      await reloadBenefits();
    } catch (error) {
      setSheet(null);
      setScanError(errorMessage(error));
    } finally {
      finish();
    }
  }

  const coverage = (
    <CoverageCard
      benefits={benefits}
      loading={syncing}
      onOpen={() => setTab(tab === "plan" ? "chat" : "plan")}
      action={tab === "plan" ? "Ask about this plan" : undefined}
    />
  );
  const choosePlan = health ? (
    <>
      <ChoosePlan
        disabled={!canChoosePlan}
        onOwnPlan={openUpload}
        onSample={() => void changePlan("sample-plan")}
      />
      {planError && !sheet && (
        <p className="error" role="alert">
          {planError}
        </p>
      )}
    </>
  ) : (
    coverage
  );
  const billSamples = samples.filter((sample) => sample.kind === "bill");
  const planSamples = samples.filter((sample) => sample.kind === "benefits");
  const suggestions = review ? BILL_SUGGESTIONS : SUGGESTIONS;

  return (
    <div className="stage">
      <aside className="demo-heading">
        <div className="desktop-brand">
          <img src="./app-icon.png" alt="" />
          ClearClaim
        </div>
        <span className="eyebrow">YOUR BENEFITS, MADE CLEAR</span>
        <h1>
          A little clarity.
          <br />A lot less worry.
        </h1>
        <p>
          Your benefits, bills, and answers.
          <br />
          All in one place.
        </p>
        <button
          className="replay"
          onClick={() => {
            setTab("home");
            setSplash(true);
          }}
        >
          <Icon name="refresh" size={17} /> Replay opening
        </button>
        <div className="desktop-note">
          iPhone-inspired web app
          <br />
          Connected to your ClearClaim backend
        </div>
      </aside>
      <div className="device">
        <div className="hardware-button one" />
        <div className="hardware-button two" />
        <div className="screen">
          <header className="statusbar">
            <span>9:41</span>
            <div className="island" />
            <div className="signals">
              <span className="signal">▂▄▆▇</span>
              <span className="battery" />
            </div>
          </header>
          <div className="app-top">
            <div className="wordmark">
              <img src="./app-icon.png" alt="" />
              ClearClaim
            </div>
            <span className="mode">
              {syncing
                ? "Connecting…"
                : health
                  ? health.gemini_enabled
                    ? "AI available"
                    : "Offline AI"
                  : "API offline"}
            </span>
          </div>
          {connectionError && (
            <div className="connection-banner" role="alert">
              <p>{connectionError}</p>
              <button disabled={busy} onClick={() => void refresh()}>
                Retry connection
              </button>
            </div>
          )}
          {pending && (
            <div className="operation-status" role="status">
              {pendingStatus(pending)}
            </div>
          )}
          <main className={`phone-content ${tab}`} ref={scroll}>
            {tab === "home" && (
              <div className="page">
                <div className="welcome">
                  <span className="eyebrow">LET’S MAKE IT CLEAR</span>
                  <h1>
                    Your health.
                    <br />
                    Your peace of mind.
                  </h1>
                  <p>Understand your plan. Know your costs.</p>
                </div>
                {notice && (
                  <p className="notice" role="status">
                    {notice}
                  </p>
                )}
                {hasPlan ? (
                  <>
                    {coverage}
                    {benefits && <DemoNote benefits={benefits} />}
                    <div className="section-heading">
                      <h2>How can we help?</h2>
                    </div>
                    <div className="action-grid">
                      <button onClick={() => setTab("chat")}>
                        <span className="action-icon">
                          <Icon name="chat" size={25} />
                        </span>
                        <strong>Ask ClearClaim</strong>
                        <span>
                          Your benefits,
                          <br />
                          in plain English
                        </span>
                        <Icon name="arrow" size={18} />
                      </button>
                      <button onClick={() => setTab("scan")}>
                        <span className="action-icon pale">
                          <Icon name="scan" size={25} />
                        </span>
                        <strong>Check a bill</strong>
                        <span>
                          A second look
                          <br />
                          at your charges
                        </span>
                        <Icon name="arrow" size={18} />
                      </button>
                    </div>
                    <button
                      className="question-card"
                      disabled={!available}
                      onClick={() => void ask(SUGGESTIONS[2])}
                    >
                      <span className="mini-icon">
                        <Icon name="spark" />
                      </span>
                      <span>
                        <small>A GOOD PLACE TO START</small>
                        <strong>Is my wellness visit covered?</strong>
                      </span>
                      <Icon name="chevron" size={17} />
                    </button>
                  </>
                ) : (
                  choosePlan
                )}
                <p className="footnote">
                  Financial and administrative guidance only. Estimates are not
                  guaranteed costs.
                </p>
              </div>
            )}
            {tab === "chat" && (
              <div className="page">
                <div className="page-title">
                  <span className="eyebrow">BENEFITS COPILOT</span>
                  <h1>A clearer answer.</h1>
                  <p>
                    {hasPlan
                      ? `Using ${plan?.plan_name}`
                      : "Choose a plan to start asking questions."}
                  </p>
                  {hasPlan && scans.length > 0 && (
                    <p className="bill-context">
                      <Icon name="scan" size={16} />
                      {scans.length > 1
                        ? `Also using your ${scans.length} saved bills`
                        : `Also using your bill from ${scans[0].provider ?? scans[0].file_name}`}
                    </p>
                  )}
                </div>
                {!hasPlan ? (
                  choosePlan
                ) : turns.length === 0 ? (
                  <>
                    <div className="chat-orb">
                      <Icon name="spark" size={32} />
                    </div>
                    <h2 className="center">What’s on your mind?</h2>
                    <p className="center muted">
                      {review
                        ? "Ask about your bill or your plan."
                        : "Include a dollar amount for a cost estimate."}
                    </p>
                    <div className="suggestion-list">
                      {suggestions.map((suggestion, index) => (
                        <button
                          key={suggestion}
                          disabled={!available}
                          onClick={() => void ask(suggestion)}
                        >
                          <Icon
                            name={["wallet", "shield", "spark", "plan"][index]}
                            size={19}
                          />
                          <span>{suggestion}</span>
                          <Icon name="plus" size={17} />
                        </button>
                      ))}
                    </div>
                  </>
                ) : (
                  <div className="turns" aria-live="polite">
                    {turns.map((turn, index) => (
                      <div key={index}>
                        <div className="user-bubble">{turn.question}</div>
                        {turn.response && (
                          <div className="answer">
                            <div className="answer-label">
                              <Icon name="spark" size={16} /> ClearClaim{" "}
                              <small>
                                {aiLabel(turn.response.demo_mode)}
                                {turn.response.bill_scan_id &&
                                  " · used your bill"}
                              </small>
                            </div>
                            <PolicyText text={turn.response.answer} />
                            {turn.response.cost_estimate && (
                              <div className="estimate">
                                <small>ESTIMATED COST TO YOU</small>
                                <strong>
                                  {money(
                                    turn.response.cost_estimate
                                      .estimated_out_of_pocket,
                                  )}
                                </strong>
                                <p>{turn.response.cost_estimate.explanation}</p>
                                <small>
                                  Simplified in-network estimate, not a quote.
                                </small>
                                <DemoNote benefits={turn.response.benefits} />
                              </div>
                            )}
                            {turn.response.sources.length > 0 && (
                              <details>
                                <summary>
                                  {turn.response.sources.length} policy{" "}
                                  {turn.response.sources.length === 1
                                    ? "source"
                                    : "sources"}
                                </summary>
                                {turn.response.sources.map((source, i) => (
                                  <blockquote key={i}>
                                    <strong>{source.document}</strong>
                                    <p>{source.snippet}</p>
                                  </blockquote>
                                ))}
                              </details>
                            )}
                          </div>
                        )}
                        {turn.error && (
                          <p className="error" role="alert">
                            {turn.error} Your question is back in the composer.
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
            {tab === "scan" && (
              <div className="page">
                <div className="page-title">
                  <span className="eyebrow">BILL & EOB SCANNER</span>
                  <h1>Let’s check that bill.</h1>
                  <p>Spot charges worth a closer look.</p>
                </div>
                {!hasPlan ? (
                  choosePlan
                ) : (
                  <>
                    <label
                      className={`scan-upload ${!available ? "disabled-upload" : ""}`}
                    >
                      <input
                        aria-label="Upload medical bill"
                        type="file"
                        accept={UPLOAD_ACCEPT}
                        disabled={!available}
                        onChange={(event) => {
                          const file = event.target.files?.[0];
                          event.target.value = "";
                          if (file) void scanBill(file);
                        }}
                      />
                      <span className="scan-symbol">
                        <Icon name="scan" size={45} />
                      </span>
                      <strong>
                        {pending === "scan"
                          ? "Reviewing your bill…"
                          : "Upload your bill"}
                      </strong>
                      <span>PDF or photo, including HEIC · up to 15 MB</span>
                      <span className="upload-pill">
                        <Icon name="upload" size={16} /> Choose a file
                      </span>
                    </label>
                    {billSamples.map((sample) => (
                      <button
                        className="secondary full sample-button"
                        key={sample.name}
                        disabled={!available}
                        onClick={() => void scanBill(undefined, sample)}
                      >
                        Try sample bill
                      </button>
                    ))}
                    {sampleError && <p className="muted">{sampleError}</p>}
                    <p className="demo-callout">
                      <Icon name="info" size={18} />
                      Bills are reviewed by AI. If AI is unavailable, only the
                      sample bill can be reviewed, and it's clearly labeled.
                    </p>
                    {scanError && (
                      <p className="error" role="alert">
                        {scanError}
                      </p>
                    )}
                    {scans.length > 1 && (
                      <section aria-label="Your saved bills">
                        <div className="section-heading">
                          <h2>Your bills</h2>
                          <span className="mode">{scans.length} saved</span>
                        </div>
                        <div className="bill-list">
                          {scans.map((scan) => (
                            <button
                              key={scan.scan_id}
                              className="bill-row"
                              aria-pressed={review?.scan_id === scan.scan_id}
                              disabled={busy}
                              onClick={() => {
                                setScanError("");
                                setReview(scan);
                              }}
                            >
                              <span className="bill-row-icon">
                                <Icon name="scan" size={18} />
                              </span>
                              <span className="bill-row-text">
                                <strong>
                                  {scan.provider ?? scan.file_name}
                                </strong>
                                <small>
                                  {shortDate(scan.scanned_at)} · You pay{" "}
                                  {money(scan.you_owe)}
                                </small>
                              </span>
                              <Icon name="chevron" size={16} />
                            </button>
                          ))}
                        </div>
                      </section>
                    )}
                    {review && (
                      <div className="scan-results" aria-live="polite">
                        <div className="section-heading">
                          <h2>Bill review</h2>
                          <span className="mode">
                            {review.demo_mode
                              ? "Sample result"
                              : "Gemini result"}
                          </span>
                        </div>
                        {review.demo_mode && (
                          <p className="notice">
                            AI is offline, so this is the saved analysis of the
                            sample bill.
                          </p>
                        )}
                        <section className="price-card">
                          <span>
                            YOUR TOTAL PRICE
                            {review.demo_mode ? " · SAMPLE" : ""}
                          </span>
                          <strong>{money(review.you_owe)}</strong>
                          <p>
                            Your share under your plan
                            {review.potential_savings > 0
                              ? ", once flagged charges are fixed"
                              : ""}
                            . The bill asks for {money(review.total_billed)}.
                          </p>
                          {benefits && (
                            <div className="price-deductible">
                              <div
                                className="price-meter"
                                role="progressbar"
                                aria-label="Deductible met"
                                aria-valuemin={0}
                                aria-valuemax={100}
                                aria-valuenow={deductiblePercent(benefits)}
                              >
                                <i
                                  style={{
                                    width: `${deductiblePercent(benefits)}%`,
                                  }}
                                />
                              </div>
                              <small>
                                {review.applied_to_deductible > 0 && (
                                  <b className="deductible-bump">
                                    +{money(review.applied_to_deductible)}
                                  </b>
                                )}
                                Deductible: {money(benefits.deductible_met)} of{" "}
                                {money(benefits.deductible_total)}
                                {demoMark(benefits, "deductible_total")} met
                              </small>
                            </div>
                          )}
                        </section>
                        <section className="savings-card">
                          <span>
                            POTENTIAL SAVINGS
                            {review.demo_mode ? " · SAMPLE" : ""}
                          </span>
                          <strong>{money(review.potential_savings)}</strong>
                          <p>
                            Flagged charges to discuss with your provider.
                            Savings are not guaranteed.
                          </p>
                        </section>
                        <div className="white-card">
                          <small>{review.provider ?? "Your bill"}</small>
                          <div className="total-line">
                            <span>Total billed</span>
                            <strong>{money(review.total_billed)}</strong>
                          </div>
                          <PolicyText text={review.summary} />
                          <p className="review-context">
                            {review.file_name} · checked against{" "}
                            {review.plan_name}
                          </p>
                        </div>
                        {review.overcharge_flags.length > 0 && (
                          <div className="flag-card">
                            <strong>Things to review</strong>
                            {review.overcharge_flags.map((flag, i) => (
                              <p key={i}>{flag}</p>
                            ))}
                          </div>
                        )}
                        <h2 className="section-label">Line items</h2>
                        {review.line_items.map((item, i) => (
                          <article className="line-item" key={i}>
                            <div className="line-code">
                              CPT {item.code}
                              <span
                                className={
                                  item.flag ? "review-badge" : "covered-badge"
                                }
                              >
                                {item.flag
                                  ? "Review"
                                  : item.covered
                                    ? "Covered"
                                    : "Check"}
                              </span>
                            </div>
                            <h3>{item.description}</h3>
                            <div className="line-money">
                              <span>
                                Billed <b>{money(item.billed)}</b>
                              </span>
                              <span>
                                Expected member cost{" "}
                                <b>
                                  {item.plan_expected === null
                                    ? "Unknown"
                                    : money(item.plan_expected)}
                                </b>
                              </span>
                            </div>
                            {item.flag && <p>{item.flag}</p>}
                          </article>
                        ))}
                        <button
                          className="primary full sample-button"
                          disabled={!available}
                          onClick={() => setTab("chat")}
                        >
                          <Icon name="chat" size={17} /> Ask about this bill
                        </button>
                        <button
                          className="secondary full sample-button"
                          disabled={busy}
                          onClick={() => setSheet("remove")}
                        >
                          Remove this bill
                        </button>
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
            {tab === "plan" && (
              <div className="page">
                <div className="page-title">
                  <span className="eyebrow">YOUR BENEFITS</span>
                  <h1>The bigger picture.</h1>
                  <p>{plan?.plan_name ?? "No plan chosen yet."}</p>
                </div>
                {notice && (
                  <p className="notice" role="status">
                    {notice}
                  </p>
                )}
                {!hasPlan ? (
                  choosePlan
                ) : (
                  <>
                    {coverage}
                    {benefits && (
                      <>
                        <DemoNote benefits={benefits} />
                        <section className="white-card plan-stats">
                          <div>
                            <span>Your coinsurance</span>
                            <strong>
                              {(benefits.coinsurance_rate * 100).toLocaleString(
                                "en-US",
                                { maximumFractionDigits: 4 },
                              )}
                              %{demoMark(benefits, "coinsurance_rate")}
                            </strong>
                          </div>
                          <div>
                            <span>Plan pays after deductible</span>
                            <strong>
                              {(
                                (1 - benefits.coinsurance_rate) *
                                100
                              ).toLocaleString("en-US", {
                                maximumFractionDigits: 4,
                              })}
                              %{demoMark(benefits, "coinsurance_rate")}
                            </strong>
                          </div>
                          <div>
                            <span>Out-of-pocket maximum</span>
                            <strong>
                              {money(benefits.oop_max)}
                              {demoMark(benefits, "oop_max")}
                            </strong>
                          </div>
                        </section>
                      </>
                    )}
                    {plan && (
                      <>
                        <div className="section-heading">
                          <h2>Active plan</h2>
                          <span className="mode">
                            {plan.source === "demo"
                              ? "Sample plan"
                              : "Uploaded plan"}
                          </span>
                        </div>
                        <div className="white-card active-plan">
                          <h3>{plan.plan_name}</h3>
                          <span className="summary-label">
                            {aiLabel(plan.demo_mode)}
                          </span>
                          <PolicyText text={plan.summary} />
                        </div>
                      </>
                    )}
                    <button
                      className="primary full sample-button"
                      disabled={!canChoosePlan}
                      onClick={openUpload}
                    >
                      <Icon name="upload" size={17} /> Upload or paste a plan
                    </button>
                    <div className="plan-controls">
                      <button
                        className="secondary"
                        disabled={busy}
                        onClick={() => void refresh()}
                      >
                        <Icon name="refresh" size={15} /> Refresh
                      </button>
                      <button
                        className="secondary"
                        disabled={!available}
                        onClick={() => {
                          setPlanError("");
                          setSheet("clear");
                        }}
                      >
                        Start over
                      </button>
                    </div>
                  </>
                )}
                <p className="footnote">
                  {privateData
                    ? "Your plan, bill scans, and chats are saved privately for this browser."
                    : "One shared plan for this server. Choosing a plan or starting over changes it for everyone."}{" "}
                  Uploaded plans start with $0 deductible met. What you owe on
                  scanned bills counts toward it; remove a bill to take it back
                  out.
                </p>
              </div>
            )}
          </main>
          {tab === "chat" && hasPlan && (
            <form
              className="composer"
              onSubmit={(event) => {
                event.preventDefault();
                void ask(question);
              }}
            >
              <div className="message-field">
                <input
                  maxLength={4000}
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  placeholder="Ask about your coverage…"
                  aria-label="Your benefits question"
                />
                <button
                  disabled={!available || !question.trim()}
                  aria-label="Send question"
                >
                  <Icon name="send" size={20} />
                </button>
              </div>
            </form>
          )}
          <nav className="bottom-nav" aria-label="Main navigation">
            {(["home", "chat", "scan", "plan"] as Tab[]).map((name, index) => (
              <button
                key={name}
                onClick={() => setTab(name)}
                className={tab === name ? "active" : ""}
                aria-current={tab === name ? "page" : undefined}
              >
                <Icon name={name} />
                <span>{["Home", "Ask", "Scan", "My plan"][index]}</span>
              </button>
            ))}
          </nav>
          <div className="home-indicator" />
          {splash && (
            <div className="splash">
              <div className="splash-center">
                <img
                  src="./app-icon.png"
                  alt="ClearClaim red bandage app icon"
                />
                <h1>ClearClaim</h1>
                <p>A little clarity goes a long way.</p>
                <div className="splash-loader">
                  <i />
                </div>
              </div>
            </div>
          )}
          <dialog
            ref={dialog}
            onCancel={(event) => {
              if (pending === "plan" || pending === "remove")
                event.preventDefault();
              else setSheet(null);
            }}
            className="policy-dialog"
          >
            <div className="section-heading">
              <h2>{sheetTitle(sheet)}</h2>
              <button
                type="button"
                className="icon-button"
                disabled={pending === "plan" || pending === "remove"}
                aria-label="Close"
                onClick={() => setSheet(null)}
              >
                <Icon name="close" />
              </button>
            </div>
            <p className="shared-warning">
              {sheet === "remove"
                ? `${review?.provider ?? review?.file_name ?? "This bill"} will be deleted${review && review.you_owe > 0 ? ", and what you owe on it will stop counting toward your deductible" : ""}.`
                : sheet === "clear"
                  ? `This removes ${privateData ? "your" : "the shared"} plan, bill scans, and chats, then returns to the welcome screen.`
                  : `This replaces ${privateData ? "your" : "the shared"} plan and clears previous chats and bill scans.`}
            </p>
            {sheet === "remove" ? (
              <button
                className="primary full"
                disabled={busy}
                onClick={() => void removeBill()}
              >
                Yes, remove it
              </button>
            ) : sheet === "clear" ? (
              <button
                className="primary full"
                disabled={busy}
                onClick={() => void changePlan("clear")}
              >
                Yes, start over
              </button>
            ) : (
              <>
                <div
                  className="upload-tabs"
                  role="group"
                  aria-label="Plan input method"
                >
                  <button
                    aria-pressed={uploadKind === "file"}
                    disabled={busy}
                    onClick={() => setUploadKind("file")}
                  >
                    PDF or photo
                  </button>
                  <button
                    aria-pressed={uploadKind === "text"}
                    disabled={busy}
                    onClick={() => setUploadKind("text")}
                  >
                    Paste text
                  </button>
                </div>
                {uploadKind === "file" ? (
                  <div>
                    <label className="pdf-upload">
                      <Icon name="upload" size={20} />
                      <span>
                        {attachedFile
                          ? attachedFile.name
                          : "Choose benefits PDF or photo"}
                      </span>
                      <input
                        aria-label="Choose plan file"
                        type="file"
                        accept={UPLOAD_ACCEPT}
                        disabled={busy}
                        onChange={(event) => {
                          setAttachedFile(event.target.files?.[0] ?? null);
                          setPlanError("");
                        }}
                      />
                    </label>
                    <p className="muted">
                      PDF, PNG, JPEG, WebP, HEIC or HEIF · up to 15 MB. Photos
                      need working Gemini vision.
                    </p>
                    <button
                      className="primary full sample-button"
                      disabled={busy || !attachedFile}
                      onClick={() => void changePlan("upload")}
                    >
                      Use this plan
                    </button>
                    {planSamples.length > 0 && (
                      <>
                        <label className="field-label">
                          Or try a sample
                          <select
                            value={sampleName}
                            disabled={busy}
                            onChange={(event) =>
                              setSampleName(event.target.value)
                            }
                          >
                            <option value="">Choose sample benefits</option>
                            {planSamples.map((sample) => (
                              <option key={sample.name} value={sample.name}>
                                {sample.name}
                              </option>
                            ))}
                          </select>
                        </label>
                        <button
                          className="secondary full"
                          disabled={busy || !sampleName}
                          onClick={() => void changePlan("sample-file")}
                        >
                          Use sample benefits
                        </button>
                      </>
                    )}
                  </div>
                ) : (
                  <form
                    onSubmit={(event) => {
                      event.preventDefault();
                      void changePlan("text");
                    }}
                  >
                    <label className="field-label">
                      Plan title
                      <input
                        maxLength={200}
                        value={title}
                        onChange={(event) => setTitle(event.target.value)}
                        placeholder="e.g. Employee benefits"
                        disabled={busy}
                      />
                    </label>
                    <label className="field-label">
                      Policy text
                      <textarea
                        required
                        rows={5}
                        maxLength={200000}
                        value={policyText}
                        onChange={(event) => setPolicyText(event.target.value)}
                        placeholder="Paste your benefits policy…"
                        disabled={busy}
                      />
                    </label>
                    <button
                      className="primary full"
                      disabled={busy || !policyText.trim()}
                    >
                      Use pasted plan
                    </button>
                  </form>
                )}
              </>
            )}
            {pending === "plan" && (
              <p className="notice" role="status">
                Reading and indexing the plan… This may take a minute or more.
              </p>
            )}
            {planError && (
              <p className="error" role="alert">
                {planError}
              </p>
            )}
          </dialog>
        </div>
      </div>
    </div>
  );
}
