<div align="center">

# 📄 DocForge

### AI-powered DOCX reverse-engineering & document assembly — now multi-user, in the cloud.

Turn a few **filled** Word documents into a reusable, layout-preserving **template**,
then generate new documents from structured data *or* plain notes — with accounts,
projects, validation, and a real Word-page preview.

<br/>

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js_14-000000?style=for-the-badge&logo=nextdotjs&logoColor=white)
![React](https://img.shields.io/badge/React_18-20232A?style=for-the-badge&logo=react&logoColor=61DAFB)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=for-the-badge&logo=typescript&logoColor=white)
![Supabase](https://img.shields.io/badge/Supabase-3FCF8E?style=for-the-badge&logo=supabase&logoColor=white)
![License: MIT](https://img.shields.io/badge/License-MIT-black?style=for-the-badge)

</div>

---

## ✨ What it does

DocForge takes 1–5 *filled* example Word documents of the same type, figures out
what content is **fixed** vs **dynamic** vs **repeatable** vs **auto**, and turns
them into a reusable, layout-preserving **template** plus structured intelligence.
You then generate new documents from structured data *or* from unstructured notes
(the AI routes content to the right fields), with validation and a review step
before anything is finalized.

It’s **privacy-aware**: with no AI key configured it runs a fully deterministic
heuristic engine — no external calls. Point it at any **OpenAI-compatible** API
(OpenAI, NVIDIA, Groq, Gemini, Mistral, Ollama, LM Studio…) to enable the LLM.

---

## 🚀 Highlights

| | |
|---|---|
| 🔐 **Accounts & multi-user** | Email/password sign-in via **Supabase Auth**; every template, project, and document is scoped to its owner. JWTs verified locally (HS256 *and* asymmetric ES256/RS256 via JWKS). |
| 📁 **Projects + inherited metadata** | Group templates into projects and define free-form key/value metadata. At generation it **pre-fills matching fields** and is exposed as `{{ variables }}` — explicit per-document values always win. |
| 🧠 **Reverse-engineer templates** | Upload filled DOCX; DocForge diffs them, classifies every element, and builds a clean `template.docx` with Jinja placeholders by editing the original OOXML **in place** (company formatting preserved). |
| ✍️ **Two generation modes** | Structured JSON/form, or unstructured text the AI router maps onto fields (with missing/ambiguous detection). |
| ✅ **Validation & compliance** | Required fields, types, dates, numbers, enums, table schema, regex — plus a side-by-side **compliance check** that diffs an uploaded doc against a template and can patch it back into shape. |
| 🗄️ **Pluggable storage** | Files live on the local filesystem (dev) **or** in **Supabase Storage** (disk-less cloud hosts) — same code, one env var. |
| ☁️ **Free cloud deploy** | One-click-ish **Render + Supabase** blueprint (Postgres + Auth + Storage), all on free tiers. See [`DEPLOY.md`](./DEPLOY.md). |
| 🎨 **Modern monochrome UI** | ElevenLabs-inspired redesign — white/black/grey in light **and** dark mode, **Geist** + **Fraunces** type, **Lucide** icons, glassy pill buttons. |

---

## 🏗️ Architecture

```
        ┌──────────────────────┐                ┌──────────────────────────────┐
        │   Next.js 14 web app │  Bearer JWT +  │        FastAPI backend       │
        │      (frontend/)     │ ─────────────► │          (backend/)          │
        │  Supabase Auth login │   JSON / REST  │  owner-scoped, JWT-verified  │
        └──────────────────────┘ ◄───────────── └──────────────────────────────┘
                   │                                    │            │
                   ▼                                    ▼            ▼
          ┌─────────────────┐                  ┌──────────────┐ ┌──────────────┐
          │  Supabase Auth  │                  │   Postgres   │ │   Storage    │
          │  (accounts/JWT) │                  │ (or SQLite)  │ │ local / S3-  │
          └─────────────────┘                  └──────────────┘ │ like bucket  │
                                                                └──────────────┘

  publish:  document_ingest → ooxml_extractor → structure_normalizer →
            multi_doc_differ → ai_classifier → template_builder → template_registry
  generate: ai_router → (project metadata merge) → assembler → validator
```

AI is used for exactly three tasks (each with a deterministic fallback):
**classify elements**, **understand sections**, **route unstructured content**.
Everything else is deterministic and unit-tested (**100+ tests**).

**Backend modules** (`backend/docforge/`):

| Module | Responsibility |
|---|---|
| `api` + `api/auth.py` | REST endpoints, background jobs, **Supabase JWT verification** (HS256 + JWKS) |
| `storage/` | **Pluggable object store** — `LocalStorage` (disk) / `SupabaseStorage` (bucket) |
| `document_ingest` | Upload validation, safe storage, zip-bomb/XXE guards |
| `ooxml_extractor` | Defensive OPC/zip reading: parts, rels, media, numbering |
| `structure_normalizer` | Normalized element tree with stable node IDs + xpaths |
| `multi_doc_differ` | Structural alignment + confidence-scored diffs |
| `ai_classifier` | FIXED/DYNAMIC/REPEATABLE/AUTO classification + fields/rules |
| `template_builder` | Build `template.docx` (docxtpl + lxml OOXML fallback) |
| `template_registry` | Versioned template packages (through the storage layer) |
| `ai_router` | Map structured/unstructured input to fields |
| `assembler` / `validator` | Deterministic DOCX rendering + rule engine |
| `services/` | Orchestration: analyze, publish, generate, **projects**, compliance, audit |

**Data model:** `User`, `Project` (owner-scoped, free-form `meta`), `Template`
(nullable `project_id` + `owner_id`), `TemplateVersion`, `GenerationRequest`,
`GeneratedDocument`, `AnalysisJob` — all per-user scoped.

---

## 🧰 Tech stack

- **Backend:** Python 3.11+, FastAPI, SQLAlchemy 2 (SQLite dev / Postgres prod),
  Pydantic v2, python-docx, docxtpl, lxml, **PyJWT** (`[crypto]`).
- **Frontend:** Next.js 14 (App Router) + React 18 + TypeScript, **Geist** +
  **Fraunces** (`next/font`), **lucide-react**, `docx-preview`, `@supabase/supabase-js`.
- **Cloud:** **Supabase** (Auth + Postgres + Storage), **Render** (hosting),
  OpenAI-compatible LLM (optional).

---

## ⚡ Quickstart (local dev)

DocForge runs fully **offline & single-user** out of the box — no Supabase or AI
key required.

**1. Backend**

```bash
cd backend
python -m venv .venv
# Windows:  .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"

cp ../.env.example .env            # defaults work out of the box (auth off, local storage)
docforge seed                       # build demo templates (optional)
docforge serve                      # API on http://localhost:8000  (docs at /docs)
```

> By default `DOCFORGE_AUTH_REQUIRED=false` → the app runs as a single local user
> with no login. Set it to `true` + Supabase env vars to enable accounts.

**2. Frontend**

```bash
cd frontend
npm install
npm run dev                         # web app on http://localhost:3000
```

With no `NEXT_PUBLIC_SUPABASE_URL` set, the UI runs in local no-auth mode. Add
Supabase env to `frontend/.env.local` to enable the login flow.

---

## ☁️ Deploy for free (Render + Supabase)

A complete, **multi-user, $0** deployment is documented step-by-step in
**[`DEPLOY.md`](./DEPLOY.md)**:

- **Supabase** (free): Postgres database + email/password **Auth** + **Storage** bucket.
- **Render** (free): backend (Docker) + frontend (Node), via the included
  [`render.yaml`](./render.yaml) blueprint.
- AI via any OpenAI-compatible provider (set `DOCFORGE_AI_*`), or leave off for
  the heuristic engine.

The backend auto-creates its tables on boot (`docforge initdb`), so deploying is
just a push + redeploy.

---

## ⚙️ Configuration

All settings are environment variables prefixed `DOCFORGE_` (see
[`.env.example`](./.env.example)). Key ones:

| Variable | Default | Purpose |
|---|---|---|
| `DOCFORGE_DATABASE_URL` | `sqlite:///./data/docforge.db` | DB (use a Postgres URL in prod) |
| `DOCFORGE_AUTH_REQUIRED` | `true` | require a Supabase JWT (`false` = local single-user) |
| `DOCFORGE_SUPABASE_URL` | — | Supabase project URL (JWKS + storage) |
| `DOCFORGE_SUPABASE_JWT_SECRET` | — | legacy HS256 secret (new projects use JWKS — leave blank) |
| `DOCFORGE_SUPABASE_SERVICE_ROLE_KEY` | — | server-side key for Storage (secret) |
| `DOCFORGE_STORAGE_BACKEND` | `local` | `local` or `supabase` |
| `DOCFORGE_CORS_ALLOW_ORIGINS` | `*` | allowed frontend origin(s) |
| `DOCFORGE_AI_ENABLED` | `false` | enable the LLM (else heuristic) |
| `DOCFORGE_AI_BASE_URL` / `_MODEL` / `_API_KEY` | OpenAI | any OpenAI-compatible provider |

Frontend (`frontend/.env.local`): `NEXT_PUBLIC_API_BASE_URL`,
`NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`.

---

## 🔌 API (selected)

All data routes require `Authorization: Bearer <supabase-jwt>` (unless auth is off).

| Method & path | Purpose |
|---|---|
| `GET  /api/health` | health + AI status (public) |
| `GET  /api/me` | current signed-in user |
| `POST /api/templates/analyze` | upload 1–5 DOCX → analysis (review) job |
| `POST /api/templates` | publish a reviewed job (optional `project_id`) |
| `GET  /api/templates` · `GET /api/templates/{id}` | list / detail (owner-scoped) |
| `POST /api/templates/{id}/generate` · `/route` · `/validate` | generate / route / validate |
| `POST /api/templates/{id}/compliance[/fix]` | compliance check + in-place fix |
| `GET  /api/projects` · `POST /api/projects` | list / create projects |
| `GET  /api/projects/{id}` · `PATCH` · `DELETE` | detail (with templates) / edit metadata / delete |
| `POST · DELETE /api/projects/{pid}/templates/{tid}` | assign / unassign a template |
| `GET  /api/generations/{id}[/download]` | generation status / download DOCX |

Interactive docs: **http://localhost:8000/docs**.

---

## 🧪 Testing

```bash
cd backend
pytest                 # unit + integration + API tests (100+)
ruff check docforge    # lint

cd ../frontend
npx tsc --noEmit && npm run build
```

Coverage includes auth (401, per-user isolation, JWKS), storage round-trips
(local + mocked Supabase), projects (CRUD, assign, metadata inheritance &
override), and the full analyze → publish → generate flow.

---

## 🗂️ Project layout

```
DocForge/
├── backend/
│   ├── docforge/            # the platform (modules above) + storage/ + api/auth.py
│   ├── tests/               # unit + integration + api + fixtures
│   ├── alembic/             # DB migrations (prod path)
│   ├── Dockerfile           # FastAPI image (+ Postgres driver, optional LibreOffice)
│   └── pyproject.toml
├── frontend/                # Next.js 14 app — monochrome UI, Lucide, Supabase auth
│   ├── app/                 # App Router pages (incl. /projects, /login)
│   ├── components/          # UI + page components (icons.tsx = Lucide hub)
│   └── lib/                 # api client, types, auth context, supabase client
├── render.yaml              # Render blueprint (backend + frontend)
├── DEPLOY.md                # free Render + Supabase deployment guide
├── docker-compose.yml · Makefile · .env.example
```

---

## 🔒 Security & privacy

Per-user data isolation (owner-scoped, no-leak 404s), Supabase JWT verification,
file-type validation, upload size limits, zip-bomb & path-traversal guards,
hardened (no-DTD/no-network) XML parsing, secrets from env only, document text
kept out of logs, and an audit trail for AI decisions and template publication.

## 📜 License

MIT.
