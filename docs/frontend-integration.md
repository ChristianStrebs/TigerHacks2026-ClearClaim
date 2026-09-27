# ClearClaim: phone UI, chat memory, and targeted backend fixes

## Reviewed base

Repository: https://github.com/ChristianStrebs/TigerHacks2026-ClearClaim

Base commit: **f2c4a72749f372b561cce018ce15013c2f058e13**. Both main and backend pointed here when inspected. This base includes the merged web prototype and chat-history API. The phone UI retains the requested Home/Ask/Scan/My plan design and supplied icon animation.

This ZIP contains **only changed/new files**, plus changes.patch, a binary-safe patch against that exact base. Unlike the previous package, it includes targeted backend changes and a new Supabase migration. It is not a full repository or a standalone offline HTML app.

No remote files, branches, commits, pushes, PRs, or live database changes were made.

## Implemented changes

### Frontend

- Preserves the phone layout, launch animation, coverage summary, chat, bill scanner, and plan controls.
- Connects launch data, plan text/PDF/photo upload, reset, samples, estimates, and savings to FastAPI.
- Sends successful question/answer history in chronological order: at most 20 messages and 4,000 Unicode characters per message. The backend uses the last 10. Failed requests, document cards, bill results, and plan summaries are excluded.
- Clears prior conversation/results when a plan is replaced or a refresh detects another browser's change.
- Preserves per-response offline/Gemini labels and marks missing plan figures with Demo*.
- Displays fractional percentages and handles a zero deductible without dividing by zero.
- Retains HEIC MIME normalization, file validation, recoverable errors, a 180-second AI timeout, and Vite dev/preview API proxies.
- Retains the merged prototype's source components without mounting them; their API calls remain type-compatible.

### Targeted backend fixes

1. **Zero is valid.** $0 deductibles, 0% coinsurance, and $0 out-of-pocket maximum are preserved. Missing/invalid values use labeled defaults.
2. **Explicit percentage units.** coinsurance_percent=1 means 1%, .5 means 0.5%, and 100 means 100%. The field no longer guesses whether input is a fraction. This matches the extraction prompt's contract; fraction callers must convert to percentages.
3. **Missing values are null.** Gemini's prompt and nullable schema distinguish absent figures from zero. Offline summaries retain zeros and recognize decimal percentages and 100%.
4. **Finite validation.** NaN, infinity, negative, boolean, and string extracted numeric fields are rejected.
5. **Configured sample summary.** Main summary figures come from settings. The bundled policy itself remains the ACME sample; keep default demo settings for consistency or upload a real plan.
6. **Transactional index replacement.** Supabase uses one replace_documents RPC. Insert failure rolls back deletion. The in-memory store builds replacement data before swapping and synchronizes chunk/matrix access.
7. **Clean database errors.** Replacement failure returns 503 and does not publish a new in-memory plan. There is no destructive fallback when the migration is absent.
8. **RPC permissions.** The new migration revokes PUBLIC/anon/authenticated execution from replacement and similarity-search functions, then grants service_role. Revoking only named browser roles left inherited PUBLIC permissions in the original migration.

Production backend scope: six existing Python files, approximately +97/-45 lines, plus a 37-line migration. Regression tests are separate. No account system, persistence model, or endpoint redesign was added.

## Larger work deliberately not implemented

These require coordinated schema/backend changes, beyond the small fixes authorized:

- **Per-user plans/accounts:** one shared active plan and index remain. Upload/reset still replaces the entire dedicated demo index. Independent users' private documents must not be mixed there.
- **Durable metadata:** services.plan lives in memory. Supabase can retain documents across restart while numeric metadata resets to the sample. Plan metadata, active-document identity, and startup restore need a shared design.
- **Multi-worker/concurrent consistency:** transactional index replacement does not combine in-memory plan metadata and database content into one transaction. Concurrent users or a timeout after a successful database commit may leave them inconsistent. Use one worker and one presenter changing plans for this demo.
- **Claims accounting:** the existing estimate treats deductible spend as prior out-of-pocket spend. A claims ledger or separate out-of-pocket progress is a larger feature; estimates remain simplified.

These are not claimed as fixed.

## Apply on a review branch

Use a clean working tree. Keep existing work intact. If the repo is already cloned, open its root; otherwise:

~~~sh
git clone https://github.com/ChristianStrebs/TigerHacks2026-ClearClaim.git
cd TigerHacks2026-ClearClaim
git fetch origin
git status
git rev-parse origin/main
~~~

Confirm origin/main matches the reviewed commit. If it advanced, review the new changes first; do not overwrite newer work or use force/reset to make the patch fit.

~~~sh
git switch -c feature/clearclaim-phone-ui-integration origin/main
~~~

Extract the ZIP **outside** the repo. Replace the example path with the actual extracted location:

~~~powershell
git apply --check "C:\Users\YOUR_NAME\Downloads\ClearClaim-Source\changes.patch"
git apply "C:\Users\YOUR_NAME\Downloads\ClearClaim-Source\changes.patch"
git diff --check
git diff --stat
~~~

The check changes no files. If it reports a conflict or existing added file, inspect it rather than forcing the patch. Use either the patch or matching overlay files, not both. Do not commit the downloaded patch itself.

If an earlier standalone demo was manually installed, its frontend/src/demo.ts and frontend/src/sample-policy.txt are obsolete and absent from this base. Confirm that situation before removing them. VITE_DEMO_MODE is no longer used.

## Run and verify

Backend, Windows PowerShell:

~~~powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest -q
uvicorn app.main:app --host 127.0.0.1 --port 8000
~~~

On macOS/Linux use python3 and source .venv/bin/activate.

Frontend, second terminal:

~~~sh
cd frontend
pnpm install --frozen-lockfile
pnpm run build
pnpm dev
~~~

Open http://localhost:5173. Without keys, the real backend provides labeled offline responses. For the production build locally, run pnpm preview and open http://localhost:4173 with FastAPI running.

Configuration:

- VITE_API_BASE_URL: empty for same-origin /api; use an HTTPS backend origin for cross-origin hosting, set before building.
- VITE_API_PROXY_TARGET: dev/preview proxy target; defaults to http://127.0.0.1:8000, read from environment or frontend .env.
- Backend keys, Supabase service-role credentials, and CORS_ORIGINS stay on the backend. Do not commit .env or put service-role credentials in frontend variables.
- Physical phone: open http://LAPTOP_LAN_IP:5173 on the same Wi-Fi; Vite proxies to FastAPI locally.
- Hosting needs a reverse proxy for /api or a configured cross-origin backend. The development proxy is not a production hosting configuration.

### Supabase migration

The owner should review and apply **supabase/migrations/0002_atomic_document_replacement.sql**, after 0001_init.sql, in the intended **dedicated ClearClaim database**, before using the patched backend with Supabase. Use the team's migration process or SQL editor; do not reset/recreate the database.

The migration creates/replaces functions and adjusts permissions. Applying it does not replace document rows. Subsequent plan upload/reset replaces the shared index transactionally.

Without migration 0002, Supabase plan replacement fails cleanly. In-memory mode needs no migration. No live migration was applied during this work.

## Commit and request review

Review the diff first. If only this package's changes are present, use honest logical commits:

~~~sh
git add backend supabase/migrations/0002_atomic_document_replacement.sql
git diff --cached --stat
git commit -m "Fix plan number parsing and atomic index replacement"
git add frontend
git diff --cached --stat
git commit -m "Connect phone UI to active plans and chat history"
git add CHANGELOG.md docs
git commit -m "Document integration, verification, and remaining limits"
git push -u origin feature/clearclaim-phone-ui-integration
~~~

These are instructions, not actions already taken. They group real changes; they do not imply a fabricated development timeline. Follow the hackathon's AI-use disclosure rules.

Open a GitHub pull request:

- Base: main, or the owner's explicitly requested integration branch.
- Compare: feature/clearclaim-phone-ui-integration.
- Title: Integrate phone UI and chat memory; fix plan parsing and index replacement.
- Description: explain the phone design, history, backend fixes, migration 0002, tests, and deferred persistence/accounts. State that the changes were AI-assisted.
- Ask the owner to review the migration/backend changes; leave merging to them.

If you cannot push, use a fork and a cross-repository PR into the owner's main.

## Verification

- Frontend TypeScript and Vite production build passed; dependencies/lockfile unchanged.
- **61 backend tests passed**, including upstream chat history and new zero/1%/fractional/100% parsing, null-vs-zero schema, replacement failure, and plan-preservation checks. One existing Starlette/httpx deprecation warning remains.
- Browser + FastAPI checks passed: launch, sample PDF ingestion, balances, chat sources, follow-up request history, bounds/Unicode limits, reset/history clearing, $565 sample bill review, upload errors, HEIC failure, HTTP 503 recovery, and mobile layout.
- A $0 deductible/1% plan produces a $10 estimate for $1,000, without a demo marker on extracted fields.
- Actual migrations passed in local PGlite PostgreSQL with pgvector: success, invalid-vector and duplicate-ID rollback, empty input protection, service-role execution, and denied anon/authenticated RPC access.
- Live Gemini, live Supabase, real HEIC vision, remote hosting, and multi-user consistency were not tested. Run python -m app.smoke with configured credentials and repeat the live flow before presenting.

The ZIP also contains a prompt for step-by-step Windows/GitHub guidance in regular ChatGPT.
