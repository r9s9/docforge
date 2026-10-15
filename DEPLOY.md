# Deploying DocForge

Pick the setup that fits. Everything with accounts uses
[Supabase](https://supabase.com) for sign-in, the database and file storage.

| Setup | Accounts | Good for |
|---|---|---|
| [Your computer](README.md#run-your-own-copy) | No | Trying it out, development |
| [Docker Compose](#docker-compose) | No | One user on your own server |
| [Vercel + Supabase](#vercel--supabase) | Yes | A public instance. This is what app.docforge.live runs. |
| [Render + Supabase](#render--supabase) | Yes | A public instance from the included blueprint |

Before anyone else signs up, work through
[Before you open sign-ups](#before-you-open-sign-ups).

---

## Supabase

You need this for every setup with accounts.

1. **Create a project** at [supabase.com](https://supabase.com) and save the
   database password.
2. **Copy these values** (Project Settings → API Keys, and Data API):
   - Project URL: `https://<ref>.supabase.co`
   - The **anon** (publishable) key. It is safe in the browser.
   - The **service_role** (secret) key. It is server-side only.
   - The JWT secret, only if your project still uses the legacy shared secret.
     New projects use JWT signing keys, which the backend checks through the
     project URL with nothing to copy.
3. **Copy the database address** (Connect, in the top bar):
   - **Session pooler**, port `5432`, for long-running servers and one-off
     commands.
   - **Transaction pooler**, port `6543`, for serverless hosts such as Vercel.
4. **Create a Storage bucket** named `docforge` and keep it **Private**. The
   backend reads and writes it with the service_role key; browsers only get
   short-lived signed links.
5. **Lock the Data API.** DocForge talks to Postgres directly and never uses
   Supabase's Data API. Its tables live in the `public` schema, which the Data
   API exposes to anyone holding the public anon key. Either turn the Data API
   off, or enable row level security on every table, without policies, by
   running this in the SQL editor (again after every schema change):

   ```sql
   do $$
   declare t record;
   begin
     for t in select tablename from pg_tables where schemaname = 'public' loop
       execute format('alter table public.%I enable row level security', t.tablename);
     end loop;
   end $$;
   ```

   The backend connects as the tables' owner, so it is not affected.
6. **Set up sign-in** (Authentication):
   - Keep the **Email** provider on.
   - Under URL Configuration, set the **Site URL** to your app's address and add
     it to the **Redirect URLs**. Confirmation links in emails go there.
   - **Confirm email** stops people signing up with someone else's address. It
     needs working email: Supabase's built-in sender is for testing only and
     sends just a few messages an hour, so add your own SMTP server (Project
     Settings → Authentication → SMTP) first.
   - Leave **CAPTCHA** off. The sign-up form does not send a CAPTCHA token yet,
     so turning it on would block every new account.
7. **Create the tables.** Docker and Render do this on every start. For Vercel,
   run it once from your machine against the session pooler:

   ```bash
   cd backend
   DOCFORGE_DATABASE_URL="postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres" \
     .venv/bin/docforge initdb
   ```

   On Windows PowerShell, set `$env:DOCFORGE_DATABASE_URL = "..."` and run
   `.\.venv\Scripts\docforge.exe initdb`.

---

## Vercel + Supabase

Two Vercel projects from this one repository. File uploads and downloads go
straight between the browser and Supabase Storage through signed links, so
large documents never hit Vercel's 4.5 MB request limit.

### Backend project

Import the repository, set **Root Directory** to `backend` (Vercel detects
FastAPI from `main.py`), and add these environment variables:

| Variable | Value |
|---|---|
| `DOCFORGE_SERVERLESS` | `true` |
| `DOCFORGE_ENV` | `production` |
| `DOCFORGE_DATA_DIR` | `/tmp` |
| `DOCFORGE_AUTH_REQUIRED` | `true` |
| `DOCFORGE_DATABASE_URL` | the transaction pooler address (port `6543`) |
| `DOCFORGE_STORAGE_BACKEND` | `supabase` |
| `DOCFORGE_SUPABASE_URL` | `https://<ref>.supabase.co` |
| `DOCFORGE_SUPABASE_SERVICE_ROLE_KEY` | the service_role key |
| `DOCFORGE_SUPABASE_STORAGE_BUCKET` | `docforge` |
| `DOCFORGE_SUPABASE_JWT_SECRET` | only for legacy projects |
| `DOCFORGE_CORS_ALLOW_ORIGINS` | your app's address, e.g. `https://app.docforge.live` |
| `DOCFORGE_FREE_AI_ENABLED` | `true`, to give every account free AI actions |
| `DOCFORGE_FREE_AI_PROVIDER` | `anthropic` |
| `DOCFORGE_FREE_AI_BASE_URL` | `https://api.anthropic.com` |
| `DOCFORGE_FREE_AI_MODEL` | `claude-haiku-5-5` |
| `DOCFORGE_FREE_AI_LIMIT` | `10` |
| `DOCFORGE_FREE_AI_API_KEY` | your Anthropic key, scoped to one workspace |

Deploy, then open `https://<backend>/api/health`. It should answer with
`"status": "ok"` and the current version.

### Frontend project

Import the same repository again, set **Root Directory** to `frontend`, and add:

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | the backend's address |
| `NEXT_PUBLIC_SUPABASE_URL` | `https://<ref>.supabase.co` |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | the anon key |

`NEXT_PUBLIC_*` values are built into the app, so redeploy the frontend after
you change them.

### Connect the two

1. Add your domain to the frontend project (for example `app.docforge.live`).
2. Set `DOCFORGE_CORS_ALLOW_ORIGINS` on the backend to exactly that address, and
   redeploy the backend.
3. Put the same address in Supabase's Site URL and Redirect URLs.

### Limits on Vercel

- **No PDF export.** It needs LibreOffice, which can't run on Vercel. DOCX
  downloads work, and the app hides the PDF button.
- **The in-app Logs page is sparse.** Each serverless instance keeps its own
  short buffer. Full logs are in the Vercel dashboard.
- **Cold starts** add a second or two to the first request after a quiet spell.

---

## Render + Supabase

[`render.yaml`](render.yaml) defines both services. In Render, choose **New →
Blueprint**, connect the repository and apply it. Then fill in the values the
blueprint leaves blank: the session pooler address (Render can't reach
Supabase's IPv6-only direct connection), the Supabase URL and keys, the
frontend's address for CORS, and the backend's address for the frontend.
Redeploy both once the two addresses are known.

Free Render services sleep after about 15 minutes without traffic, so the first
request after that takes 30 to 50 seconds.

---

## Docker Compose

```bash
docker compose up --build        # app on http://localhost:3000
```

This runs one user without sign-in, with data in a Docker volume. For
accounts, use Vercel or Render with Supabase: the frontend image is built
without sign-in settings.

**PDF export** works on Docker if you build the backend with LibreOffice:

```bash
docker compose build --build-arg INSTALL_LIBREOFFICE=true backend
```

It adds about 1 GB to the image.

---

## AI

Every user without AI gets the deterministic engine, so the app always works.
On top of that:

- **Free AI actions.** With `DOCFORGE_FREE_AI_*` set, every account gets
  `DOCFORGE_FREE_AI_LIMIT` actions on your key. Users never see the key.
- **Their own key.** Users add a provider and key in **Settings → LLM Settings**.
  It is stored on the server and never returned to the browser.
- **One shared key** (`DOCFORGE_AI_*`) is used only when the free tier is off,
  which suits a private team instance.

A user's own key always wins. When the free actions run out and there is no own
key, that user is back on the deterministic engine.

---

## Before you open sign-ups

- [ ] **Privacy policy.** Replace [`frontend/lib/legal/privacy.ts`](frontend/lib/legal/privacy.ts)
      with your own. The shipped one describes docforge.live only.
- [ ] **Data API locked** (Supabase step 5).
- [ ] **Email.** Custom SMTP set up, and Confirm email on.
- [ ] **CORS** set to your exact app address, not `*`.
- [ ] **Keys.** Every secret lives only in the host's settings, and any key that
      was ever pasted into a chat, file or commit has been rotated.
- [ ] **Spend limit.** If you offer free AI actions, set a monthly limit on that
      key in the provider's console.

## Check it end to end

1. Open the app, create an account (tick the privacy policy), and confirm it
   from the email.
2. **New Template**: upload two examples, then review and publish.
3. **Generate Document**: fill it in and download the `.docx`.
4. **Compliance Check**: upload an edited copy, then fix it.
5. Create a second account. It sees an empty dashboard and gets a 404 on the
   first account's template address.
6. **Settings → Profile**: delete the second account.

## Troubleshooting

- **Analysis never finishes on Vercel.** `DOCFORGE_SERVERLESS` must be `true`;
  otherwise analysis waits for a background thread that never runs.
- **`/api/health` fails with a database error.** Use the transaction pooler
  (port `6543`) on Vercel, and check the password has no trailing space.
- **CORS errors on upload or download** (requests to `*.supabase.co`). Open a
  signed link directly in a tab to check it works, then allow your app's
  address for Storage in Supabase.
- **New users never get a confirmation email.** Supabase's built-in sender is
  for testing only; add your own SMTP server.
