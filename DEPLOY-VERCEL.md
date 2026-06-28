# Deploying DocForge to Vercel

DocForge deploys as **two Vercel projects from this one repo**:

| Project | Root Directory | What it is |
|---------|----------------|------------|
| `docforge-backend`  | `backend`  | FastAPI as a single Python Vercel Function (all routes under `/api`) |
| `docforge-frontend` | `frontend` | Next.js app |

Database, Auth and file Storage are **Supabase** (unchanged from the Render setup).
The browser uploads/downloads files **straight to Supabase Storage via signed
URLs**, so file bytes never hit the function — this is what keeps uploads under
Vercel's 4.5 MB request-body cap.

---

## 0. Prerequisites

- The code is pushed to GitHub (`r9s9/docforge`). Vercel deploys from Git.
- A Supabase project (you already have one for Render) with:
  - a **Storage bucket** named `docforge` (Private),
  - **Auth** enabled (email/password),
  - the Postgres connection strings and API keys (Supabase → Project Settings).
- The backend installed locally (the existing `backend/.venv`) so you can create
  the database tables once.

---

## 1. One-time Supabase prep

### 1a. Create the tables (run once, locally)
On Vercel the function does **not** create tables on boot (serverless mode). Do it
once from your machine, pointed at the production database. Use the **Session
pooler** URI (port **5432**) or the direct connection for this one-off.

**Windows (PowerShell):**
```powershell
cd backend
$env:DOCFORGE_DATABASE_URL = "postgresql://postgres.<ref>:<pwd>@aws-0-<region>.pooler.supabase.com:5432/postgres"
.\.venv\Scripts\docforge.exe initdb
```

**macOS / Linux (bash):**
```bash
cd backend
DOCFORGE_DATABASE_URL="postgresql://postgres.<ref>:<pwd>@aws-0-<region>.pooler.supabase.com:5432/postgres" \
  .venv/bin/docforge initdb
```
You should see the tables created. (If you already ran this for Render, the
schema is current and this is a no-op.)

### 1b. Note the values you'll paste into Vercel
- `SUPABASE_URL` = `https://<ref>.supabase.co`
- **anon / publishable key** (browser-safe)
- **service_role key** (server-side secret)
- **Transaction pooler** DB URI (port **6543**) — for the serverless backend:
  `postgresql://postgres.<ref>:<pwd>@aws-0-<region>.pooler.supabase.com:6543/postgres`

---

## 2. Deploy the BACKEND project

1. Vercel → **Add New… → Project** → import `r9s9/docforge`.
2. **Root Directory → `backend`**. Framework auto-detects as **FastAPI** (it finds
   `main.py`). Leave build/output as detected.
3. Add **Environment Variables** (Production), then Deploy:

| Key | Value |
|-----|-------|
| `DOCFORGE_SERVERLESS` | `true` |
| `DOCFORGE_ENV` | `production` |
| `DOCFORGE_DATA_DIR` | `/tmp` |
| `DOCFORGE_AUTH_REQUIRED` | `true` |
| `DOCFORGE_STORAGE_BACKEND` | `supabase` |
| `DOCFORGE_SUPABASE_STORAGE_BUCKET` | `docforge` |
| `DOCFORGE_DATABASE_URL` | the **6543** transaction-pooler URI |
| `DOCFORGE_SUPABASE_URL` | `https://<ref>.supabase.co` |
| `DOCFORGE_SUPABASE_SERVICE_ROLE_KEY` | service_role key |
| `DOCFORGE_SUPABASE_JWT_SECRET` | (optional — only for legacy HS256 projects) |
| `DOCFORGE_CORS_ALLOW_ORIGINS` | `*` for now (tighten in step 4) |
| `DOCFORGE_FREE_AI_ENABLED` | `true` |
| `DOCFORGE_FREE_AI_PROVIDER` | `anthropic` |
| `DOCFORGE_FREE_AI_BASE_URL` | `https://api.anthropic.com` |
| `DOCFORGE_FREE_AI_MODEL` | `claude-haiku-4-5-20251001` |
| `DOCFORGE_FREE_AI_LIMIT` | `10` |
| `DOCFORGE_FREE_AI_API_KEY` | your `sk-ant-…` key (secret) |

4. After deploy, note the URL, e.g. `https://docforge-backend.vercel.app`, and test:
   `GET https://docforge-backend.vercel.app/api/health` → should return JSON with
   `"version": "0.5.0"`.

> **Plan note:** Hobby allows a 300 s max function duration (already set in
> `backend/vercel.json`). On **Pro** you can raise it to 800 s in the project's
> **Settings → Functions** if you expect very large documents / slow models.

---

## 3. Deploy the FRONTEND project

1. Vercel → **Add New… → Project** → import the **same** repo again.
2. **Root Directory → `frontend`**. Framework = Next.js (auto).
3. Environment Variables (Production), then Deploy:

| Key | Value |
|-----|-------|
| `NEXT_PUBLIC_API_BASE_URL` | the backend URL from step 2 (e.g. `https://docforge-backend.vercel.app`) |
| `NEXT_PUBLIC_SUPABASE_URL` | `https://<ref>.supabase.co` |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | anon / publishable key |

4. Note the frontend URL, e.g. `https://docforge-frontend.vercel.app`.

---

## 4. Wire the two together

1. **Backend CORS:** set `DOCFORGE_CORS_ALLOW_ORIGINS` to the exact frontend origin
   (e.g. `https://docforge-frontend.vercel.app`) and **redeploy the backend**.
2. **Supabase Auth:** Supabase → Authentication → URL Configuration → add the
   frontend URL to **Site URL** and **Redirect URLs**.

---

## 5. Verify end-to-end

On the live frontend:
1. Sign up / sign in.
2. **New Template** → upload a `.docx` (try one **larger than 4.5 MB** with images
   to confirm direct-to-storage upload works). Analysis should complete.
3. Publish, then **Generate** a document and **Download** it.
4. **Compliance** → upload a doc, run a check, and **Fix** it.

If uploads or downloads fail with a browser **CORS** error, see Troubleshooting.

---

## What changed for Vercel (FYI)

- **Direct-to-Supabase file I/O.** `POST /api/uploads/sign` issues a signed URL; the
  browser PUTs the file to Supabase, then calls the `*-refs` endpoints with the
  storage key. Downloads/previews redirect to signed URLs. Bytes bypass the 4.5 MB
  function cap.
- **`DOCFORGE_SERVERLESS=true`** makes template analysis run *inline* (a background
  thread wouldn't survive the function freezing) and skips boot-time table
  creation/maintenance (you ran `initdb` in step 1a).
- **DB pooling**: Postgres uses a `NullPool` + `pool_pre_ping`; pair it with the
  **transaction pooler (6543)** so short-lived instances don't exhaust connections.

## Known limitations on Vercel

- **PDF export is unavailable** (needs LibreOffice, which can't run on Vercel). The
  DOCX preview/download work; the PDF endpoint returns a clear 501.
- **In-app Logs page is sparse.** It reads an in-memory buffer that's per-instance
  and ephemeral on serverless. Full logs are in the Vercel dashboard (Functions →
  Logs). (Backing it with a table would be a follow-up.)
- **Cold starts** add a second or two to the first request after idle.

## Troubleshooting

- **CORS error on download/preview (fetch to `*.supabase.co`):** Supabase Storage is
  permissive by default, but if your project blocks it, allow your frontend origin
  for Storage. Confirm the signed URL opens directly in a browser tab.
- **CORS error on upload (PUT to `*.supabase.co`):** same fix; the preflight is a
  normal `OPTIONS` Supabase should answer.
- **`/api/health` 500 about the database:** check the DB URI uses the **6543**
  pooler and the password is correct (no trailing newline in the env var).
- **Analysis seems to hang:** confirm `DOCFORGE_SERVERLESS=true` is set on the
  backend (without it, analysis is queued to a thread that never runs on Vercel).
- **"AI is off":** the global key is intentionally disabled; the free tier (Haiku)
  and per-user keys (Settings → AI) provide AI. Confirm `DOCFORGE_FREE_AI_API_KEY`.
