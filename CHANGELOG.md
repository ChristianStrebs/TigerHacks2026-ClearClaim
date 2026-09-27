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
