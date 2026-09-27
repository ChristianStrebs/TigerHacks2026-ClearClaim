# Building a client for the ClearClaim API

How the web app talks to the backend, for anyone building another client (like the
mobile app). Exact request and response fields are in `frontend/src/types.ts` and at
http://localhost:8000/docs; what changed recently is in [CHANGELOG.md](../CHANGELOG.md).

## Run it locally

Backend (Windows PowerShell; on macOS or Linux use `python3` and
`source .venv/bin/activate`):

~~~powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --port 8000
~~~

Frontend, in a second terminal:

~~~sh
cd frontend
pnpm install
pnpm dev        # http://localhost:5173
~~~

Without keys, everything still works with labeled offline answers and in-memory data.

## Configuration

| Where | Setting | What it's for |
| --- | --- | --- |
| `backend/.env` | `GEMINI_API_KEY` | Live Gemini. Empty means offline answers. |
| `backend/.env` | `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` | Saved data per visitor. Empty means one in-memory member. |
| `backend/.env` | `CORS_ORIGINS` | Browser origins allowed to call the API. |
| `frontend/.env.local` | `VITE_API_BASE_URL` | Backend URL. Empty means same-origin `/api`, proxied by Vite. |
| `frontend/.env.local` | `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY` | Must match the backend's Supabase settings. |

Only publishable keys go in the frontend. Never commit `.env` files.

## Sessions

When Supabase is on, each visitor signs in anonymously with the Supabase client (no
login screen). Send the access token on every call except `/api/health` and
`/api/samples`:

~~~
Authorization: Bearer <Supabase access token>
~~~

A `401` means the token is missing or expired: refresh the session and retry once. Row
level security keeps each visitor's plan, bills, and chats private. When Supabase is off,
no token is needed.

## The flow

1. **Start.** `GET /api/health` shows whether Gemini and Supabase are on. `GET /api/plan`
   returns the visitor's plan, or `source: "none"` with no benefits when they haven't
   chosen one yet.
2. **Choose a plan.** `POST /api/plan/sample`, `POST /api/plan/text`, or
   `POST /api/plan/upload` (multipart `file`). Chat and bill scans return `409` until a
   plan is chosen. Changing or clearing the plan (`POST /api/plan/clear`) deletes its
   bills and chats.
3. **Scan a bill.** `POST /api/eob/scan` (multipart `file`) returns the review: line
   items with flags, `you_owe`, `potential_savings`, `applied_to_deductible`, and
   `rights` (patient protections with source links). `GET /api/eob/scans` lists the
   latest 5; `DELETE /api/eob/scans/{scan_id}` removes one.
4. **Fix a bill.** `POST /api/eob/scans/{scan_id}/dispute` returns a letter, call script,
   checklist, and deadline note. It's written fresh each time and not saved.
5. **Chat.** `POST /api/chat` with `{message, history}`. `history` is earlier turns, oldest
   first, up to 20. The response has `answer`, `sources`, `cost_estimate`, `bill_scan_id`,
   and `steps` (the tools the AI used, for a "How I answered" list).
   `GET /api/chat/history` restores the conversation after a refresh.

Sample PDFs for demos come from `GET /api/samples` and `GET /api/samples/{name}`.

## Uploads

PDF, PNG, JPEG, WebP, HEIC, or HEIF, up to 15 MB. Some browsers leave HEIC files without a
type, so the web app fills it in from the file extension.

## Errors

Errors come back as `{"detail": "..."}` with a message you can show as-is.

| Status | Meaning |
| --- | --- |
| `400` | Empty or unreadable file |
| `401` | Session missing or expired |
| `404` | That bill or sample doesn't exist |
| `409` | No plan chosen yet |
| `413` | File over 15 MB |
| `415` | Unsupported file type |
| `422` | Not a benefits document or medical bill, or invalid input |
| `503` | AI service or saved data unreachable; try again |

## Timeouts and AI labels

AI calls (chat, scans, plan uploads, dispute kits) can take a minute or more, so the web
app waits up to 180 seconds for them and 20 seconds for everything else. Responses include
`demo_mode`: when it's `true`, the answer came from offline logic or a template instead
of Gemini, and the UI should say so.

## Not advice

ClearClaim gives administrative and financial guidance only. Show a short "general
information, not legal advice" note next to rights findings and dispute letters.
