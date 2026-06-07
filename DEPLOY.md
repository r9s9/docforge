# Deploying DocForge for free (Render + Supabase)

This guide stands up a **public, multi-user** DocForge for **$0**:

- **Render** (free) runs the backend (FastAPI) and the frontend (Next.js).
- **Supabase** (free) provides the **database** (Postgres), **accounts** (Auth),
  and **file storage** (template packages, uploads, generated docs).

Free-tier caveats to expect: Render free services **sleep after ~15 min idle**
(the first request after that takes ~30–50s to wake), and Supabase pauses a
project after ~1 week of inactivity. Because files live in Supabase Storage (not
on Render's disk), nothing is lost when a service restarts.

> **AI note:** your local LM Studio model can't be reached from the cloud. The
> hosted app runs in **offline heuristic mode** by default (no AI). To enable
> smart classification/routing, set the `DOCFORGE_AI_*` vars to a cloud LLM
> (OpenAI/Anthropic — pay per token). See step 5.

---

## 1. Create the Supabase project

1. Sign up at <https://supabase.com> → **New project**. Pick a region near you
   and set a database password (save it).
2. When it's ready, open **Project Settings → API** and copy:
   - **Project URL** → `https://<ref>.supabase.co`
   - **anon public** key (safe for the browser)
   - **service_role** key (⚠️ server-side secret — never in the frontend)
   - **JWT secret** (under "JWT Settings")
3. **Database connection string** — open **Project Settings → Database →
   Connection string → URI**, and choose the **Session pooler** tab. It looks
   like:
   ```
   postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
   ```
   Use the **Session pooler** (IPv4, port 5432) — the "direct" connection is
   IPv6-only and Render can't reach it.

## 2. Create the Storage bucket

1. In Supabase → **Storage → New bucket**.
2. Name it **`docforge`**. Keep it **Private** (the backend reads/writes it with
   the service-role key; users never access it directly).

## 3. Configure Auth (email + password)

1. Supabase → **Authentication → Providers → Email**: ensure it's enabled.
2. For the smoothest demo, **Authentication → Sign In / Providers → Email** and
   turn **"Confirm email" OFF** (users can sign in immediately). Turn it back on
   later and configure SMTP for production.
3. (Recommended for a public app) **Authentication → Attack Protection**: enable
   a CAPTCHA (Turnstile/hCaptcha) to stop bot signups.

## 4. Deploy to Render with the Blueprint

The repo includes `render.yaml`, which defines both services.

1. Push the repo to GitHub (already at `https://github.com/r9s9/docforge`).
2. Go to <https://dashboard.render.com> → **New → Blueprint**, connect the repo,
   and apply. Render creates **docforge-backend** and **docforge-frontend**.
3. Set the environment variables Render left blank (marked `sync: false`):

   **docforge-backend**
   | Variable | Value |
   |---|---|
   | `DOCFORGE_DATABASE_URL` | the Session-pooler URI from step 1.3 |
   | `DOCFORGE_SUPABASE_URL` | `https://<ref>.supabase.co` |
   | `DOCFORGE_SUPABASE_JWT_SECRET` | the JWT secret |
   | `DOCFORGE_SUPABASE_SERVICE_ROLE_KEY` | the **service_role** key |
   | `DOCFORGE_CORS_ALLOW_ORIGINS` | the frontend URL (fill after it deploys, e.g. `https://docforge-frontend.onrender.com`) |

   **docforge-frontend**
   | Variable | Value |
   |---|---|
   | `NEXT_PUBLIC_API_BASE_URL` | the backend URL, e.g. `https://docforge-backend.onrender.com` |
   | `NEXT_PUBLIC_SUPABASE_URL` | `https://<ref>.supabase.co` |
   | `NEXT_PUBLIC_SUPABASE_ANON_KEY` | the **anon** key |

4. The two URLs depend on each other, so: deploy once, copy each service's URL,
   set `DOCFORGE_CORS_ALLOW_ORIGINS` (backend) and `NEXT_PUBLIC_API_BASE_URL`
   (frontend), then **trigger a redeploy** of both (the frontend must rebuild
   because `NEXT_PUBLIC_*` is baked in at build time).

## 5. (Optional) Enable AI

On **docforge-backend** set:
```
DOCFORGE_AI_ENABLED=true
DOCFORGE_AI_BASE_URL=https://api.openai.com/v1      # or Anthropic-compatible
DOCFORGE_AI_MODEL=gpt-4o-mini
DOCFORGE_AI_API_KEY=<your key>                       # secret
```
Without these, DocForge uses its deterministic heuristic engine (no external
calls, no cost).

## 6. Verify

1. Open the frontend URL → you should land on the **login** page.
2. **Create account** → you're signed in and the dashboard is empty.
3. Create a template (upload example DOCX) → it appears, and is stored in the
   Supabase `docforge` bucket (check **Storage** in Supabase).
4. Generate a document and download it.
5. Sign out, create a **second** account → its dashboard is empty and it can't
   open the first account's template URL (404). Per-user isolation works.

---

## Optional: enable PDF export

PDF export (DOCX→PDF) needs LibreOffice, which is heavy for the free tier and
off by default. To include it, build the backend image with:
```
--build-arg INSTALL_LIBREOFFICE=true
```
(In Render: backend service → **Settings → Docker Build Args**.) Without it, the
PDF button returns a clear "install LibreOffice" message; DOCX download always
works.

## Known limitations (fine for a demo, revisit for scale)

- Free Render services sleep when idle (cold starts).
- AI provider settings are machine-global (set via env), not per-user.
- A single backend instance only (file storage is in Supabase, but there's no
  horizontal-scale story yet).
