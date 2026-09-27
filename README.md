# ClearClaim — Healthcare Benefits Copilot

> TigerHacks 2026 · Medical / Health track · MLH "Best Use of Gemini API"

ClearClaim is an AI-powered **healthcare benefits copilot**. It turns dense,
jargon-filled insurance policies into plain-English answers and flags likely
overcharges on medical bills — focused strictly on the **administrative and
financial** side of healthcare (no clinical/diagnostic advice).

## Core features

1. **Contextual RAG chat** — Ask questions like _"How much will my knee surgery
   cost?"_. ClearClaim retrieves the relevant parts of your benefits PDF and uses
   your deductible status to compute an out-of-pocket estimate.
2. **EOB / bill scanner** — Upload a photo of an Explanation of Benefits or a
   medical bill. Gemini vision extracts the line items, checks them against your
   plan, and flags duplicates and overcharges.

## Tech stack

| Layer     | Choice                                                      |
| --------- | ---------------------------------------------------------- |
| Frontend  | React 19 + TypeScript + Vite                               |
| Backend   | Python 3.12 + FastAPI                                      |
| AI        | Google Gemini (`gemini-3.8-flash`, `gemini-embedding-001`) |
| Vector DB | Supabase / pgvector (with an in-memory fallback)           |

The current Gemini models are read from env vars, so upgrading is a one-line
change (see `backend/.env.example`).

## Demo mode (no secrets required)

The app is **fully runnable with zero credentials**. When `GEMINI_API_KEY` is
not set, the backend uses deterministic offline responses (hashed embeddings +
canned answers) and an in-memory vector store, so the whole UI is clickable for
development and demos. The header shows a **Demo mode** / **Gemini live** badge
so it is always clear which mode is active.

## Project layout

```
backend/            FastAPI service
  app/
    routers/        /api/health, /api/chat, /api/documents, /api/eob
    services/       Gemini client, vector store, ingestion, benefits math
    data/           bundled sample benefits policy (auto-seeded)
  tests/            pytest suite (runs fully offline)
frontend/           Vite + React + TypeScript client
supabase/
  migrations/       pgvector schema + match_documents RPC (RLS enabled)
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

| Method | Path                    | Purpose                                  |
| ------ | ----------------------- | ---------------------------------------- |
| GET    | `/api/health`           | Service status, active models, mode      |
| POST   | `/api/chat`             | RAG answer + sources + cost estimate     |
| POST   | `/api/documents`        | Ingest raw policy text                   |
| POST   | `/api/documents/upload` | Ingest a policy PDF                       |
| POST   | `/api/eob/scan`         | Analyze an uploaded bill/EOB image or PDF |
| GET    | `/api/plan`             | Active plan: numbers, summary, demo flags |
| POST   | `/api/plan/upload`      | Replace the plan from a benefits PDF/photo |
| POST   | `/api/plan/reset`       | Go back to the sample plan               |
| GET    | `/api/samples`          | List demo PDFs (bill, benefits)          |
| GET    | `/api/samples/{name}`   | Download a demo PDF                      |

Request/response shapes, mobile integration notes, and what changed recently are in
[CHANGELOG.md](CHANGELOG.md).

## Testing

```bash
cd backend && .venv/bin/pytest      # backend tests (offline)
cd frontend && pnpm run build       # type-check + production build
```

## Security notes

- The Supabase `service_role` key is server-only and never shipped to the browser.
- The `documents` table has Row Level Security enabled; browser clients cannot
  read benefits content directly.
- ClearClaim provides administrative/financial guidance only — not medical advice.
