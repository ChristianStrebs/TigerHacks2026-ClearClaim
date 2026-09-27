# ClearClaim — Healthcare Benefits Copilot

> TigerHacks 2026 · Financial Freedom in Healthcare track · MLH "Best Use of Gemini API"

ClearClaim is an AI-powered **healthcare benefits copilot**. It turns dense,
jargon-filled insurance policies into plain-English answers, flags likely
overcharges on medical bills, and helps you fix them. It sticks to the
**administrative and financial** side of healthcare (no clinical or diagnostic advice).

## Core features

1. **Your plan, read for you.** Upload a benefits PDF or photo, paste the text, or try
   the sample plan. Gemini pulls out the deductible, coinsurance, and out-of-pocket max
   and writes a plain-language summary.
2. **Bill scanner.** Upload a medical bill or Explanation of Benefits. Gemini vision
   reads each line, checks it against your plan, and flags duplicates and overcharges.
   You see what you should really owe, and saved bills count toward your deductible.
3. **Your rights.** Plain rules (not the AI) check each bill against patient
   protections like the No Surprises Act and free preventive care, with a link to the
   official source.
4. **Fix this bill.** A dispute letter, a phone script for the billing office, and a
   checklist, ready to copy, download, or email. It still works from a template when
   the AI is unavailable.
5. **Chat that uses tools.** Ask things like _"What would a $3,000 MRI cost me?"_.
   Gemini decides whether to search your plan, read your bill, check your rights, or
   run ClearClaim's cost calculator. Each answer shows a "How I answered" list, and
   the calculator does all the math.

Rights and dispute features are general information, not legal advice.

## Tech stack

| Layer     | Choice                                                      |
| --------- | ---------------------------------------------------------- |
| Frontend  | React 19 + TypeScript + Vite                               |
| Backend   | Python 3.13 + FastAPI                                      |
| AI        | Google Gemini (`gemini-3.8-flash`, `gemini-embedding-001`) |
| Data      | Supabase: Postgres, pgvector, anonymous sign-in, row level security (in-memory fallback) |

The current Gemini models are read from env vars, so upgrading is a one-line
change (see `backend/.env.example`).

## Demo mode (no secrets required)

The app is **fully runnable with zero credentials**. When `GEMINI_API_KEY` is
not set, the backend uses deterministic offline responses (hashed embeddings,
canned answers, and saved readings of the sample bills), and without Supabase it
keeps data in memory, so the whole UI is clickable for development and demos. The
header shows **AI available** or **Offline AI**, and each answer says whether Gemini
wrote it, so it's always clear which mode is active.

## Project layout

```
backend/            FastAPI service
  app/
    routers/        /api/health, /api/chat, /api/eob, /api/plan, /api/samples
    services/       Gemini client, chat agent, storage, rights rules, dispute kit,
                    bill and benefits math
    data/           sample plan text, patient rights rules, sample PDFs
  tests/            pytest suite (runs fully offline)
frontend/           Vite + React + TypeScript client
supabase/
  migrations/       per-member tables, pgvector search, row level security
.cursor/            Cloud Agent environment config + install script
```

## Getting started

### Prerequisites

- Python 3.11+ and `python3-venv`
- Node 20+ and `pnpm`

### 1. Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # optional: add GEMINI_API_KEY / Supabase creds
uvicorn app.main:app --reload --port 8000
```

API docs are served at http://localhost:8000/docs.

### 2. Frontend

```bash
cd frontend
pnpm install
cp .env.example .env          # optional
pnpm dev                      # http://localhost:5173
```

The Vite dev server proxies `/api` to `http://localhost:8000`, so no extra
configuration is needed for local development.

### One-command setup

```bash
bash .cursor/install.sh       # installs backend + frontend dependencies
```

## Enabling the real integrations

1. **Gemini** — Get a key from [Google AI Studio](https://aistudio.google.com/app/apikey)
   and set `GEMINI_API_KEY` in `backend/.env`. Chat, embeddings, and the bill
   scanner will switch from demo mode to live Gemini calls automatically.
2. **Supabase / pgvector** — Create a project, apply the migrations in
   `supabase/migrations/`, and turn on Authentication → Sign In / Providers →
   "Allow anonymous sign-ins". Set `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` in
   `backend/.env`, and `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` in
   `frontend/.env.local`. Each browser then gets a private anonymous session, and its
   plan, bill scans, and chats are saved in Postgres behind row level security.

## Deploy (optional)

Everything above runs locally; hosting is only needed for a public link. When you want
one, the backend can run on Render and the frontend on Vercel using the included
`render.yaml` and `frontend/vercel.json`.

1. **Backend (Render).** New → Blueprint → pick this repo. Render reads `render.yaml`.
   Enter `GEMINI_API_KEY`, `SUPABASE_PUBLISHABLE_KEY`, and, once the frontend is up,
   `CORS_ORIGINS` (the exact Vercel URL, no trailing slash). Check
   `https://<service>.onrender.com/api/health`.
2. **Frontend (Vercel).** New Project → this repo → Root Directory `frontend`. Set
   `VITE_API_BASE_URL` to the Render URL, plus `VITE_SUPABASE_URL` and
   `VITE_SUPABASE_PUBLISHABLE_KEY`. Vercel reads `frontend/vercel.json`.
3. **Supabase.** Raise Authentication → Rate Limits → anonymous sign-ins so judges on
   the same Wi-Fi aren't blocked.

Render's free tier sleeps when idle. Open `/api/health` a couple of minutes before a
demo to wake it.

## API reference

| Method | Path                              | Purpose                                      |
| ------ | --------------------------------- | -------------------------------------------- |
| GET    | `/api/health`                     | Service status, active models, storage mode  |
| POST   | `/api/chat`                       | Answer with sources, cost estimate, and steps |
| GET    | `/api/chat/history`               | Saved conversation for the current plan      |
| GET    | `/api/plan`                       | Active plan: numbers, summary, demo flags    |
| POST   | `/api/plan/sample`                | Use the sample plan                          |
| POST   | `/api/plan/text`                  | Replace the plan from pasted text            |
| POST   | `/api/plan/upload`                | Replace the plan from a benefits PDF or photo |
| POST   | `/api/plan/clear`                 | Remove the plan and everything saved with it |
| POST   | `/api/eob/scan`                   | Review a bill or EOB image or PDF            |
| GET    | `/api/eob/scans`                  | The latest 5 saved bill reviews              |
| GET    | `/api/eob/scans/{scan_id}`        | One saved bill review                        |
| POST   | `/api/eob/scans/{scan_id}/dispute` | Dispute letter, call script, and checklist  |
| DELETE | `/api/eob/scans/{scan_id}`        | Remove one bill                              |
| DELETE | `/api/eob/scans`                  | Remove every bill                            |
| GET    | `/api/samples`                    | List demo PDFs (bills, benefits)             |
| GET    | `/api/samples/{name}`             | Download a demo PDF                          |

When Supabase is configured, every route except `/api/health` and `/api/samples` needs
`Authorization: Bearer <Supabase access token>`.

Request/response shapes, mobile integration notes, and what changed recently are in
[CHANGELOG.md](CHANGELOG.md).

## Testing

```bash
cd backend && .venv/bin/pytest      # backend tests (offline)
cd frontend && pnpm run build       # type-check + production build
```

## Security notes

- No Supabase `service_role` key is used anywhere. The backend forwards each member's
  own access token, so row level security keeps every visitor's plan, bills, and chats
  private.
- Secrets live in `backend/.env` and `frontend/.env.local`, which git ignores.
- ClearClaim provides administrative and financial guidance only: not medical advice,
  and its rights and dispute features are not legal advice.
