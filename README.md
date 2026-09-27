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

Run ClearClaim on your own computer in about five minutes. You'll use two terminals:
one for the backend and one for the frontend.

### Prerequisites

- [Python 3.12 or newer](https://www.python.org/downloads/) (tested on 3.13)
- [Node.js](https://nodejs.org/) 20.19+ or 22.12+
- pnpm: `npm install -g pnpm`
- Optional: a free Gemini API key from
  [Google AI Studio](https://aistudio.google.com/app/apikey). Without one the app runs
  in demo mode (see [What works without a key](#what-works-without-a-key)).

### 1. Get the code

```bash
git clone https://github.com/ChristianStrebs/TigerHacks2026-ClearClaim.git
cd TigerHacks2026-ClearClaim
```

### 2. Start the backend (terminal 1)

macOS / Linux:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

Windows (PowerShell):

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --port 8000
```

If PowerShell blocks `Activate.ps1`, run
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once and try again.

The copied `.env` already points at the shared ClearClaim Supabase project, so your
plan, bills, and chats are saved online, privately for your browser. To use the real AI,
put your key in `backend/.env` as `GEMINI_API_KEY=...` and restart the backend.

Check http://localhost:8000/api/health. You should see `"status":"ok"`,
`"supabase_enabled":true`, and `"gemini_enabled":true` if your key was picked up. API
docs are at http://localhost:8000/docs.

### 3. Start the frontend (terminal 2)

```bash
cd frontend
pnpm install
pnpm dev
```

Open http://localhost:5173. The frontend needs no `.env`: the Vite dev server forwards
`/api` to the backend on port 8000, and the app gets its Supabase settings from the
backend.

### What works without a key

- **No Gemini key:** the sample plan and both sample bills work fully, including the
  rights check, cost math, and "Fix this bill" templates. Chat gives canned answers.
  Your own bills and photos need a key, and the app says so.
- **With a Gemini key:** everything, including your own plan and bill uploads and the
  tool-using chat.
- **Without Supabase** (both Supabase lines in `backend/.env` blank): your plan, bills,
  and chats are kept in memory for one local user and are cleared when the backend
  restarts.

### Troubleshooting

- **Port 8000 or 5173 already in use:** close whatever is using it; both ports are fixed.
- **The app can't reach the server:** make sure the backend terminal is still running.
- **"We couldn't start your private session":** Supabase limits new guest sign-ins per
  network. Wait a bit and refresh, or blank both Supabase lines in `backend/.env` to run
  fully offline.
- **Try it on your phone:** on the same Wi-Fi, open `http://<your computer's IP>:5173`
  (find the IP with `ipconfig` on Windows or `ifconfig` on macOS). Allow Node.js through
  your firewall if asked.

## Enabling the real integrations

1. **Gemini** — Get a key from [Google AI Studio](https://aistudio.google.com/app/apikey)
   and set `GEMINI_API_KEY` in `backend/.env`. Chat, embeddings, and the bill
   scanner will switch from demo mode to live Gemini calls automatically.
2. **Supabase / pgvector** — `backend/.env.example` already uses the shared ClearClaim
   project. To use your own instead, create a project, apply the migrations in
   `supabase/migrations/`, turn on Authentication → Sign In / Providers → "Allow
   anonymous sign-ins", and set `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` in
   `backend/.env`. The web app reads them from `/api/health`. Each browser gets a private
   anonymous session, and its plan, bill scans, and chats are saved in Postgres behind
   row level security.

## Deploy (optional)

Everything above runs locally; hosting is only needed for a public link. When you want
one, the backend can run on Render and the frontend on Vercel using the included
`render.yaml` and `frontend/vercel.json`.

1. **Backend (Render).** New → Blueprint → pick this repo. Render reads `render.yaml`.
   Enter `GEMINI_API_KEY`, `SUPABASE_PUBLISHABLE_KEY`, and, once the frontend is up,
   `CORS_ORIGINS` (the exact Vercel URL, no trailing slash). Check
   `https://<service>.onrender.com/api/health`.
2. **Frontend (Vercel).** New Project → this repo → Root Directory `frontend`. Set
   `VITE_API_BASE_URL` to the Render URL. Vercel reads `frontend/vercel.json`.
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

With the backend's virtual environment active:

```bash
cd backend && pytest              # backend tests (offline, no keys needed)
cd frontend && pnpm run build     # type-check + production build
```

## Security notes

- No Supabase `service_role` key is used anywhere. The backend forwards each member's
  own access token, so row level security keeps every visitor's plan, bills, and chats
  private.
- Secrets live in `backend/.env` and `frontend/.env.local`, which git ignores.
- ClearClaim provides administrative and financial guidance only: not medical advice,
  and its rights and dispute features are not legal advice.
