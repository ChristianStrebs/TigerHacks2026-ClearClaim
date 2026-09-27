# Changelog

What changed in ClearClaim, newest first. Every merge into `main` adds an entry here
so the frontend/mobile side can see new or changed API behavior without reading diffs.

## Branches

| Branch | Owner | What lives there |
| --- | --- | --- |
| `main` | shared | Last merged, working state. Branch off this. |
| `backend` | backend | FastAPI + Gemini work. Only touches `backend/`, `CHANGELOG.md`, and repo config. |
| your mobile branch | mobile | The mobile app. Keep it in its own folder (e.g. `mobile/`) so merges never overlap. |
| `frontend-web-prototype` | reference only | Parked web UI (splash, chat, + menu, bill card). Not planned for merge; borrow ideas or copy. |

Before merging into `main`: merge `main` into your branch, run the tests, then merge.
Because backend and mobile work live in different folders, these merges should not conflict.

---

## [Unreleased] - `demo-ready` branch - 2026-09-27

Not yet merged into `main`.

### Added

- **Private saved data per browser (Supabase).** Each browser gets an anonymous Supabase
  session, so there's no login page. Its plan, plan search index, last 5 bill scans, and
  chat history are saved in Postgres and come back after a refresh. Row level security
  keeps every visitor's rows private. Without Supabase settings the backend falls back to
  one shared in-memory plan, which is what the tests use.
- **Send the session token.** When Supabase is on, every `/api/*` call except `/api/health`
  and `/api/samples` needs `Authorization: Bearer <Supabase access token>`. A missing or
  expired token gets `401`, and the web app signs in again and retries once. If the
  database can't be reached, the response is `503`.
- **Choose how to start.** Nothing loads automatically. `POST /api/plan/sample` loads the
  labeled sample plan (`/api/plan/reset` still works). `POST /api/plan/clear` removes the
  plan and everything saved with it. Chat and bill scans return `409` until a plan is chosen.
- **Unrelated uploads are rejected.** Plans or bills that aren't health documents get `422`
  with a plain-language message, and the current plan is kept.
- **Saved bill scans.** Scans now include `scan_id`, `file_name`, `scanned_at`, and the plan
  name. `GET /api/eob/scans` lists the latest 5, `GET /api/eob/scans/{scan_id}` fetches one,
  and `DELETE /api/eob/scans` clears them. Chat uses the latest scan automatically.
- **Saved chat.** Every answered question is saved. `GET /api/chat/history` returns
  `[{"question", "response"}]`, oldest first (up to 50).
- **Database migrations** in `supabase/migrations/`: tables `plans`, `plan_chunks` (pgvector),
  `bill_scans`, and `chat_messages`, plus the `replace_plan` and `match_plan_chunks`
  functions. Changing or clearing a plan deletes its chunks, scans, and chats.
- **Patient rights rules** in `backend/app/data/patient_rights.json`: 7 plain-language rules
  (preventive care, No Surprises Act emergency, specialist, and air ambulance protections,
  the ground ambulance gap, duplicate charges, and appeals). Each has what you should owe,
  what to do, and an official source link.
- **Bills count toward the deductible.** Each scan now returns `you_owe` (what the member
  should pay once flagged charges are fixed), `applied_to_deductible`, and `file_sha256`.
  The `benefits` in `GET /api/plan` and `POST /api/chat` add up `applied_to_deductible`
  across every saved bill, so coinsurance never counts toward the deductible. Scanning the
  same file again replaces the earlier scan instead of counting it twice. Gemini is told
  the deductible left before the bill, so its per-line amounts match the member's progress.
- **Remove one bill.** `DELETE /api/eob/scans/{scan_id}` returns `204` (or `404`), and the
  bill stops counting toward the deductible.
- **Web app: your bills and total price.** The Scan tab lists saved bills so earlier ones
  can be reopened or removed. Each review starts with a "Your total price" card showing
  what you owe, how much it added to the deductible, and the deductible meter. Home shows
  "Your bill added $X to your deductible." Chat sees up to 5 recent bills, not just the
  latest.
- **Line item details for patient protections.** Each `line_items` entry now also has
  `network` (`"in"`, `"out"`, or `"unknown"`), `facility_in_network` (`true`, `false`, or
  `null`), `emergency`, `preventive`, and `provider_type` (for example `"facility"`,
  `"anesthesiology"`, `"air_ambulance"`, or `"other"`). Gemini fills them from the bill.
  Unrecognized values fall back to `"unknown"`, `null`, `false`, or `"other"` instead of
  dropping the charge.
- **Patient rights on every bill.** Each scan now returns `rights`: the protections that
  may apply, as `{rule_id, title, explanation, you_should_owe, action, lines,
  source_name, citation_url}`. `lines` names the charges each one covers, like
  `"Anesthesia (00142)"`. Gemini only reads the facts off the bill; plain rules decide
  which protection applies, so the same bill always gets the same answer. The chat sees
  these findings too. Scans saved earlier return `rights: []`.
- **Second sample bill: a surprise bill.** `surprise-bill.pdf` is a $2,700 bill from an
  out-of-network anesthesiologist at an in-network surgery center. It scans to the No
  Surprises Act protection, with or without live AI: at most $1,780 owed (the in-network
  share on the sample plan) and $920 to question. Gemini is told protected out-of-network
  lines still carry in-network cost sharing, never $0.
  Each sample in `GET /api/samples` now has a `label` for buttons and menus. The web app
  shows one "Try sample" button per sample bill.
- **Web app: "Your rights" on each bill.** When a scan finds a protection, the review shows
  a "Your rights" card after the savings: what the protection is, which charges it covers,
  what you should owe, what to do, and a link to the official source. A note says it's
  general information, not legal advice.
- **Dispute kit.** `POST /api/eob/scans/{scan_id}/dispute` returns `{letter, call_script,
  checklist, deadline_note, demo_mode}` for a saved bill. Gemini writes it from the bill,
  its patient protections, and the plan. When the AI is unavailable, a template fills in
  the provider, every flagged charge, and each protection with its source, so the kit always
  works. Personal details stay as `[Your name]`, `[Account number]`, and similar
  placeholders. Surprise bills also point to the No Surprises Help Desk (1-800-985-3059).
  Nothing is saved; the kit is written fresh each time. Returns `404` for an unknown scan
  and `409` before a plan is chosen.
- **Optional hosting configs.** `render.yaml` (backend on Render) and `frontend/vercel.json`
  (frontend on Vercel), with steps in the README's "Deploy (optional)" section. The app
  still runs fully locally without them.

### Changed

- `GET /api/health` now returns `supabase_enabled` and `storage` (`"in-memory"` or
  `"supabase"`) instead of `benefits` and `indexed_chunks`. Read plan numbers from
  `GET /api/plan`.
- Config: set `SUPABASE_URL` (base URL, no `/rest/v1`) and `SUPABASE_PUBLISHABLE_KEY` in
  `backend/.env`, and `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` in
  `frontend/.env.local`. The service role key is no longer used. In the Supabase dashboard,
  turn on Authentication → Sign In / Providers → "Allow anonymous sign-ins".

### Removed

- `/api/documents` and the old shared index migrations (`0001_init.sql`,
  `0002_atomic_document_replacement.sql`).
- The optional procedure cost field in the web chat. The backend still accepts
  `billed_amount`, and it also reads a dollar amount from the question itself.

### Fixed

- Opening the app right after signing in no longer fails with `503`. Supabase sometimes
  rejects a brand-new token as "issued at future" when its clocks differ by a second; the
  backend now waits a second and retries (up to twice) instead of giving up.
- `CORS_ORIGINS` entries with a trailing slash (e.g. `https://clearclaim.vercel.app/`) now
  work. Before, the browser's origin wouldn't match and every request would be blocked.
- Blank questions and questions over 4,000 characters now get `422` right away. Before,
  a long question was answered and then failed to save.
- Pasted plan text is trimmed and limited to 200,000 characters. Titles are limited to 300.
- Files whose contents don't match their type (a text file renamed `.pdf`, a damaged PDF)
  get `400` with a plain message instead of "the AI service is unavailable".
- Scanned PDFs whose text layer is only page numbers are now read as images.
- Long plan booklets no longer fail: embeddings are sent in batches of 100, and long
  unbroken text is split so it fits the database.
- Bill amounts written as `"$1,180.50"` are read correctly, and a missing total falls back
  to the sum of the line items instead of crashing.
- Session tokens allow 30 seconds of clock difference. When a token is rejected, the web
  app renews the same anonymous session instead of starting a new one, so saved data isn't
  lost.
- A rejected bill scan no longer hides the previous saved review in the web app.
- Answers render `*italics*`, `* ` bullets, and `#` headings instead of showing symbols.

---

## Proposed review branch — phone UI and targeted fixes

Not yet merged. Based on f2c4a72749f372b561cce018ce15013c2f058e13.

- Integrate the phone-style UI with active-plan APIs and bounded chat history.
- Preserve zero plan figures, use explicit percentages, and represent missing AI-extracted figures as null.
- Replace the shared index transactionally via migration 0002_atomic_document_replacement.sql; restrict replacement/search RPCs to service_role.
- Add regression tests and integration instructions in docs/frontend-integration.md.
- Accounts, per-user indexing, and durable active-plan metadata remain deferred.

---

## [Unreleased] - `backend` branch - 2026-09-26

### Added

- **Chat memory.** `POST /api/chat` accepts an optional `history`: earlier messages, oldest
  first, as `[{"role": "user" | "assistant", "text": "..."}]` (max 20; the last 10 are used).
  Follow-ups like "What about a $5,000 one?" then work. Nothing is stored on the server, so
  the app keeps the conversation and sends it with each question. Send only question and
  answer text, not plan or bill cards.
- **Your plan, from a PDF or photo.** `POST /api/plan/upload` takes a benefits PDF or a photo
  (PNG, JPEG, WEBP, HEIC). Gemini reads the deductible, coinsurance, and out-of-pocket max and
  writes a plain-language summary. The uploaded plan becomes the active plan for chat and bill
  scans. Any number Gemini can't find stays at its demo value and is listed in
  `benefits.demo_fields` (see "Demo* label" below).
- **Paste plan text.** `POST /api/plan/text` with `{"title": "...", "text": "..."}` does the same
  as an upload for copied policy text. If no numbers are found, the summary says so and all
  three numbers are listed in `demo_fields`.
- **Plan numbers in health.** `GET /api/health` now includes `benefits`, so one call on app
  launch can show the deductible bar and the "Gemini live" badge together.
- **Read or reset the plan.** `GET /api/plan` returns the active plan. `POST /api/plan/reset`
  goes back to the bundled sample plan (ACME Corp Health Plan) — use it between demo visitors.
- **Money at risk on bill scans.** `POST /api/eob/scan` now returns `potential_savings`: the total
  the member may not owe (duplicates, preventive care billed to them, upcoding). This is the
  headline number to show big. Lines the plan covers in full are always flagged, so the total
  matches the line items.
- **Sample files.** `GET /api/samples` lists two demo PDFs; `GET /api/samples/{name}` downloads
  one. Upload `sample-bill.pdf` to `/api/eob/scan` ($565 at risk) and `sample-benefits.pdf` to
  `/api/plan/upload` (Tiger Health Silver PPO: $3,000 / 30% / $7,500). Good for a
  "Try a sample" button when no real document is handy.
- **Cost estimates from plain questions.** Chat pulls a dollar amount out of the message itself
  ("How much will an $18,000 knee surgery cost me?" → `cost_estimate.estimated_out_of_pocket`
  = 4840). No separate `billed_amount` field is needed.
- **General benefits questions.** Chat answers general questions ("What is a deductible?") even
  when no plan is uploaded, and invites the user to submit their benefits.
- **Gemini backup models.** If the main model is overloaded (503) or out of quota (429), the
  backend retries on `gemini-3.7-flash`, then `gemini-3.5-flash-lite`. If all fail, it returns an
  offline answer instead of an error.
- **iPhone photos.** The bill scanner and plan upload both accept `image/heic` / `image/heif`.
- **Smoke test.** `python -m app.smoke` (from `backend/`) checks that Gemini chat and embeddings
  work with the configured key.

### Changed

- `POST /api/chat` only requires `{"message": "..."}`. `billed_amount` is optional.
- Every AI response has its own `demo_mode` flag: `true` means the answer came from the offline
  fallback, not live Gemini. (Previously this only reflected whether a key was configured.)
- `benefits` in chat and plan responses now includes `demo_fields`.
- The sample bill is now a wellness visit + flu shot billed to the patient, with a duplicate
  visit charge: $565 total, all of it money at risk. Offline and live results agree.
- Plan summaries always come back as `- ` bullet lines separated by newlines.
- Chat answers use the loaded plan directly instead of hedging with "depending on your
  plan's exact rules". When a detail isn't in the plan, the answer says what's missing.

### Fixed

- Gemini outages no longer crash chat, bill scans, or startup; they fall back to demo mode.
- Uploading an empty file returns 400 instead of 500; negative `billed_amount` returns 422.
- Uploading a new plan only replaces the search index after the new one is built, so a failed
  upload never leaves chat with no plan.
- PDFs are marked binary in `.gitattributes` so Windows line-ending conversion can't corrupt them.

---

## API reference for the mobile app

Interactive docs with every schema: `http://<backend>/docs`.

| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| GET | `/api/health` | — | `gemini_enabled`, `indexed_chunks`, models, `benefits` |
| GET | `/api/plan` | — | `PlanResponse` |
| POST | `/api/plan/upload` | multipart `file` (PDF or photo) | `PlanResponse` |
| POST | `/api/plan/text` | JSON `{"title": "...", "text": "..."}` | `PlanResponse` |
| POST | `/api/plan/reset` | — | `PlanResponse` |
| POST | `/api/chat` | JSON `{"message": "...", "history": [...]}` (history optional) | `ChatResponse` |
| POST | `/api/eob/scan` | multipart `file` (PDF or photo) | `EobScanResponse` |
| GET | `/api/samples` | — | list of `{name, kind, description, url}` |
| GET | `/api/samples/{name}` | — | the PDF |

`PlanResponse`:

```json
{
  "plan_name": "TIGER HEALTH SILVER PPO",
  "source": "document",
  "benefits": {
    "deductible_total": 3000,
    "deductible_met": 0,
    "deductible_remaining": 3000,
    "coinsurance_rate": 0.3,
    "oop_max": 7500,
    "demo_fields": []
  },
  "summary": "- You pay a $3,000 deductible...\n- After that you pay 30%...",
  "demo_mode": false
}
```

`ChatResponse`: `answer` (markdown: `**bold**` and `- ` bullets only), `sources` (plan excerpts
used), `benefits`, `cost_estimate` (or `null`), `demo_mode`.

`EobScanResponse`: `provider`, `total_billed`, `potential_savings`, `summary`,
`overcharge_flags` (plain sentences), `line_items[]` with `code`, `description`, `billed`,
`plan_expected` (what the member should pay), `covered`, `flag` (reason, or `null` when fine),
and `demo_mode`.

### Integration notes

- **Reaching the backend from a phone.** `localhost` on the phone is the phone itself. Run the
  backend with `uvicorn app.main:app --host 0.0.0.0 --port 8000` and point the app at
  `http://<laptop LAN IP>:8000` (same Wi-Fi). Native apps don't need CORS.
- **Uploads.** Send `multipart/form-data` with the field name `file` and a correct MIME type.
  In React Native: `form.append("file", { uri, name: "bill.jpg", type: "image/jpeg" })`.
  Max 15 MB.
- **Demo\* label.** When `benefits.demo_fields` is non-empty, show a yellow "Demo\*" badge and
  mark those numbers with `*`. The sample plan has all three fields listed.
- **AI badge.** `demo_mode: false` → "Answered by Gemini"; `true` → "Offline answer".
- **Loading states.** Gemini calls take 3-30 seconds (longer when backups kick in). Show a
  spinner and use a client timeout of at least 60 seconds for uploads and scans.
- **One shared plan.** There are no accounts: the uploaded plan is server-wide and lives in
  memory, so it resets when the backend restarts. Call `/api/plan/reset` to start fresh.
- **Errors.** Upload and AI errors return `{"detail": "human-readable message"}`, safe to show
  as-is: 400 empty/unreadable file, 413 too large, 415 wrong file type, 422 photo couldn't be
  read, 503 AI unreachable (retry). Malformed requests (e.g. empty chat message) return 422 with
  `detail` as a list of field errors; show a generic message for those.

### Known issues

- The free Gemini tier allows about 20 requests per day on `gemini-3.8-flash`. After that the
  backup models answer, which still works but is slower. Use a paid key or a fresh key for the
  live demo.
