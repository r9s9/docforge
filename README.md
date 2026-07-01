<div align="center">

# 📄 DocForge

### Turn filled Word documents into reusable templates — with an agentic AI pipeline that actually reads, reasons about, and reviews your content.

Upload a few **filled** DOCX examples → DocForge reverse-engineers a reusable,
layout-preserving **template**. Generate new documents from a form, raw notes,
or another filled document → an AI agent **understands the content and decides
where each piece belongs**, formats it to fit, and drafts what's missing. Check
any document for compliance → a deterministic diff **plus an AI judge** tells
you what actually matters.

<br/>

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js_14-000000?style=for-the-badge&logo=nextdotjs&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=for-the-badge&logo=typescript&logoColor=white)
![Gemini](https://img.shields.io/badge/Google_Gemini-8E75B2?style=for-the-badge&logo=googlegemini&logoColor=white)
![Supabase](https://img.shields.io/badge/Supabase-3FCF8E?style=for-the-badge&logo=supabase&logoColor=white)
![Vercel](https://img.shields.io/badge/Vercel-000000?style=for-the-badge&logo=vercel&logoColor=white)
![License: MIT](https://img.shields.io/badge/License-MIT-black?style=for-the-badge)

</div>

---

## ✨ What it does

DocForge takes 1–5 *filled* example Word documents of the same type, figures
out what content is **fixed** boilerplate vs **dynamic** vs **repeatable** vs
**auto**, and turns them into a reusable, layout-preserving **template** plus
structured field intelligence — all with the original company formatting
preserved (it edits the OOXML in place, not a re-render). You then generate new
documents from a form, from pasted notes, or from another filled document, with
validation and a live Word-page preview before anything is finalized.

It's **local-first and privacy-aware**: with no AI key configured, every
feature still works via a fully deterministic heuristic engine — no external
calls. Connect **Google Gemini** (recommended), **DeepSeek**, **OpenAI**,
**Anthropic**, or any OpenAI-compatible endpoint (Ollama, LM Studio…) to turn
on the agentic AI pipeline described below. Keys are bring-your-own, stored
server-side, and never returned to the browser.

---

## 🤖 Agentic AI

DocForge doesn't just call an LLM once and hope. Every AI-touched action is a
**bounded agent loop**: the model can call tools to gather real evidence before
deciding, a second pass reviews the draft, and everything degrades safely to
deterministic heuristics if AI is off, a call fails, or the endpoint doesn't
support tool-calling.

**1. Template analysis** — *understand → classify (with tools) → self-critique*
- A reasoning pass reads the whole document first (type, sections, likely
  variable content) before any element is labeled — not a blind first-batch guess.
- Classification runs with tools: the model can pull an element's **full,
  untruncated text**, its **neighbors**, and its **cross-document diff
  evidence** instead of guessing from a 200-character snippet.
- A self-critique pass re-examines only the low-confidence/ambiguous elements
  and corrects mislabeled fields, wrong types, or vague descriptions.
- Every field gets a real, specific description (auto-written if you don't
  provide one) — that description is exactly what later drives accurate
  content placement during generation.

**2. Document generation** — *route → compose → validate*
- **Routing** decides *where* your content goes: it reads your pasted notes or
  an uploaded document's full text (nothing is truncated for the AI to see),
  compares it against every field's label, type, description, and allowed
  values, and returns a placement per field with a confidence score, an
  "ambiguous" flag, and alternative candidates when content could fit more than
  one place.
- **Composing** makes the routed values document-ready: dates normalized to
  ISO, numbers/currency cleaned up, terse notes expanded into full prose for
  long-text fields, and missing **required** fields *drafted* from context
  (flagged **"AI-drafted — review"** in the UI, never silently invented facts).
- A deterministic pass then re-validates every final value against its field's
  type/enum — a confidently-wrong self-rated placement gets its confidence
  downgraded and flagged for review rather than trusted blindly.

**3. Compliance check** — *deterministic diff + AI judge*
- The structural comparison (alignment, boilerplate match, table schema) stays
  100% deterministic and fast.
- An AI judge then reviews each detected difference and decides whether it's a
  **material violation** (missing obligation, altered required text) or a
  **benign, cosmetic difference** (rewording, whitespace, an expected variable
  value) — with a plain-English rationale, added as a fourth "semantic" score
  dimension alongside structure/fields/tables.

**Models, cost, and transparency**
- Two-tier model config: a cheap **workhorse** model for high-volume steps and
  a stronger **reasoning** model for understanding/critique/composition/judging.
  One click in Settings applies the recommended pairing:
  `gemini-2.5-flash-lite` (workhorse) + `gemini-3-flash` (reasoning) — a fast,
  1M-context, ~10× cheaper alternative to typical "budget" cloud models.
- Every AI action shows its **token usage and estimated cost** right where it
  ran (New Template, Generate, Compliance Check) plus a running total in
  Settings — no black-box spend.
- A **learning loop**: when you edit the AI's proposed fields at publish time,
  those corrections are remembered and replayed as guidance the next time you
  analyze a document of the same type.

---

## 🚀 Highlights

| | |
|---|---|
| 🧠 **Reverse-engineer templates** | Upload filled DOCX; DocForge diffs them, classifies every element with an agentic pipeline, and builds a clean `template.docx` with Jinja placeholders by editing the original OOXML **in place**. |
| ✍️ **Four ways to fill a template** | Structured form, JSON, pasted notes, or an uploaded filled document — the last two go through the routing + composing agent above. |
| ✅ **Validation & AI-judged compliance** | Required fields, types, dates, numbers, enums, table schema, regex — plus a side-by-side compliance report with an AI-explained material-vs-benign verdict per difference, and an in-place fixer. |
| 🔐 **Accounts & multi-user** | Email/password via **Supabase Auth**; every template, project, and document is owner-scoped. JWTs verified locally (HS256 + JWKS/ES256). |
| 📁 **Projects + inherited metadata** | Group templates into projects with free-form key/value metadata that pre-fills matching fields at generation time. |
| 🗄️ **Pluggable, serverless-ready storage** | Local filesystem for dev, or **Supabase Storage** with direct-to-storage signed uploads/downloads (keeps large files off the API request path entirely). |
| ☁️ **Deploy to Vercel + Supabase** | Two Vercel projects (backend + frontend) from one repo, Supabase for Postgres/Auth/Storage — see [`DEPLOY-VERCEL.md`](./DEPLOY-VERCEL.md). |
| 🎨 **Modern monochrome UI** | Light/dark, **Geist** + **Fraunces** type, **Lucide** icons, a real Word-page preview panel throughout. |

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

  analyze:  document_ingest → ooxml_extractor → structure_normalizer →
            multi_doc_differ → ai_classifier (understand→classify→critique)
            → template_builder → template_registry
  generate: ai_router (route→compose) → project-metadata merge → validator → assembler
  comply:   compliance (deterministic diff) → compliance/judge (AI verdicts)
```

**Backend modules** (`backend/docforge/`):

| Module | Responsibility |
|---|---|
| `ai/` | Shared AI core: the tool-calling agent loop (`client.py`), prompts, the tool registry (`tools.py`), token/cost accounting (`usage.py`, `pricing.py`) |
| `ai_classifier` | Template-analysis agent: understand → classify-with-tools → self-critique → field/rule derivation |
| `ai_router` | Generation agent: route content to fields, then `compose.py` refines/drafts/validates values |
| `compliance` | Deterministic structural checker + `judge.py` (AI material-vs-benign verdicts) |
| `services/learning.py` | Captures the user's field-edit corrections and replays them as few-shot guidance |
| `api` + `api/auth.py` | REST endpoints, background jobs, Supabase JWT verification (HS256 + JWKS) |
| `storage/` | Pluggable object store — local filesystem or Supabase Storage with signed URLs |
| `document_ingest` | Upload validation, safe storage, zip-bomb/XXE guards |
| `ooxml_extractor` | Defensive OPC/zip reading: parts, rels, media, numbering |
| `structure_normalizer` | Normalized element tree with stable node IDs |
| `multi_doc_differ` | Structural alignment + confidence-scored diffs across sample documents |
| `template_builder` | Builds `template.docx` (docxtpl + lxml OOXML) |
| `template_registry` | Versioned template packages, through the storage layer |
| `assembler` / `validator` | Deterministic DOCX rendering + rule engine |
| `services/` | Orchestration: analyze, publish, generate, projects, compliance, audit |

---

## 🧰 Tech stack

- **Backend:** Python 3.11+, FastAPI, SQLAlchemy 2 (SQLite dev / Postgres
  prod), Pydantic v2, python-docx, docxtpl, lxml, `httpx` (AI calls), PyJWT
  (`[crypto]`).
- **AI:** Any OpenAI-compatible endpoint or native Anthropic — in practice
  **Google Gemini** (recommended default, tiered workhorse/reasoning), **DeepSeek**,
  OpenAI, or a local server (Ollama/LM Studio). Bring your own key; nothing is
  shared or billed to you by the platform.
- **Frontend:** Next.js 14 (App Router) + React 18 + TypeScript, **Geist** +
  **Fraunces** (`next/font`), `lucide-react`, `docx-preview`, `@supabase/supabase-js`.
- **Cloud:** **Supabase** (Auth + Postgres + Storage), **Vercel** (hosting —
  two projects from one repo).

---

## ⚡ Quickstart (local dev)

DocForge runs fully **offline & single-user** out of the box — no Supabase or
AI key required.

**1. Backend**

```bash
cd backend
python -m venv .venv
# Windows:  .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"

cp ../.env.example .env            # defaults work out of the box (auth off, local storage)
docforge seed                       # build demo templates (optional)
docforge serve                      # API on http://localhost:8000 — creates tables on boot (docs at /docs)
```

> By default `DOCFORGE_AUTH_REQUIRED=false` → the app runs as a single local
> user with no login. Set it to `true` + Supabase env vars to enable accounts.

**2. Frontend**

```bash
cd frontend
npm install
npm run dev                         # web app on http://localhost:3000
```

With no `NEXT_PUBLIC_SUPABASE_URL` set, the UI runs in local no-auth mode.

**3. Turn on AI (optional)**

In the app, go to **Settings → LLM Settings → "Use recommended setup"**, paste
a Gemini API key ([get one here](https://aistudio.google.com/apikey)), and
enable it. Without a key, every feature still works via the offline heuristic
engine — just less semantically aware.

---

## ☁️ Deploy (Vercel + Supabase)

A complete deployment guide is in **[`DEPLOY-VERCEL.md`](./DEPLOY-VERCEL.md)**:

- **Supabase**: Postgres database + email/password **Auth** + a **Storage**
  bucket. Files upload/download **directly to Supabase Storage via signed
  URLs** — bytes never pass through the backend, which is what keeps large
  DOCX uploads under Vercel's request-body cap.
- **Vercel**: two projects from this one repo — `backend` (FastAPI as a Python
  function) and `frontend` (Next.js) — each with its own Root Directory.
- Run `docforge initdb` once against the production database (serverless
  functions don't create tables on boot); after that, deploying is a push +
  redeploy.

Prefer to self-host with Docker instead? `docker-compose.yml` and the two
`Dockerfile`s still work for a single always-on server; see `DEPLOY.md` for
that path.

---

## ⚙️ Configuration

All settings are environment variables prefixed `DOCFORGE_` (see
[`.env.example`](./.env.example)). Key ones:

| Variable | Default | Purpose |
|---|---|---|
| `DOCFORGE_DATABASE_URL` | `sqlite:///./data/docforge.db` | DB (Postgres in prod; use the **session pooler**, port 5432, for one-off scripts and the **transaction pooler**, port 6543, on serverless) |
| `DOCFORGE_SERVERLESS` | `false` | `true` on Vercel: runs analysis inline and skips table-creation-on-boot |
| `DOCFORGE_AUTH_REQUIRED` | `true` | require a Supabase JWT (`false` = local single-user, no login) |
| `DOCFORGE_SUPABASE_URL` | — | Supabase project URL (JWKS + storage) |
| `DOCFORGE_SUPABASE_SERVICE_ROLE_KEY` | — | server-side key for Storage (secret) |
| `DOCFORGE_STORAGE_BACKEND` | `local` | `local` or `supabase` |
| `DOCFORGE_CORS_ALLOW_ORIGINS` | `*` | allowed frontend origin(s) |
| `DOCFORGE_AI_ENABLED` | `false` | enable the LLM pipeline (else the heuristic engine) |
| `DOCFORGE_AI_BASE_URL` / `_MODEL` / `_API_KEY` | OpenAI | the workhorse model config (any OpenAI-compatible provider, or Anthropic) |
| `DOCFORGE_AI_REASONING_MODEL` | *(none — reuses the workhorse)* | a stronger model for understanding/critique/composition/judging |
| `DOCFORGE_AI_AGENT_MAX_STEPS` | `6` | cap on tool-calling iterations per agentic action |

Per-user AI provider/keys are configured in-app (**Settings**) and stored
server-side — the env vars above are process-wide defaults, not required for
users to have AI.

Frontend (`frontend/.env.local`): `NEXT_PUBLIC_API_BASE_URL`,
`NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`.

---

## 🔌 API (selected)

All data routes require `Authorization: Bearer <supabase-jwt>` (unless auth is off).

| Method & path | Purpose |
|---|---|
| `GET  /api/health` | health + AI status (public) |
| `POST /api/uploads/sign` | request a direct-to-storage signed upload URL |
| `POST /api/templates/analyze[-refs]` | upload 1–5 DOCX → the analysis agent → a review job |
| `POST /api/templates` | publish a reviewed job |
| `GET  /api/templates` · `GET /api/templates/{id}` | list / detail (owner-scoped) |
| `POST /api/templates/{id}/generate` | route → compose → validate → assemble |
| `POST /api/templates/{id}/route` | preview routing+composing without generating |
| `POST /api/templates/{id}/route-document[-refs]` | map an uploaded filled document onto a template |
| `POST /api/templates/{id}/compliance[-refs]` | deterministic diff + AI judge verdicts |
| `POST /api/templates/{id}/compliance/fix[-refs]` | in-place fix of changed/missing boilerplate |
| `GET/PUT /api/settings` | per-user AI provider config + token-usage totals |
| `GET  /api/projects` · `POST /api/projects` | list / create projects |
| `GET  /api/generations/{id}[/download]` | generation status / download DOCX (or `.pdf`) |
| `GET  /api/logs` | recent server-side log entries for the signed-in user |

Interactive docs: **http://localhost:8000/docs**.

---

## 🧪 Testing

```bash
cd backend
pytest                 # unit + integration + API tests (148+)
ruff check docforge    # lint
mypy docforge          # types

cd ../frontend
npx tsc --noEmit && npm run build
```

Coverage includes the agentic AI core (tool-use loop + capability fallback,
token/cost accounting, the compose/critique/judge passes, learning capture),
auth (401s, per-user isolation, JWKS), storage round-trips, and the full
analyze → publish → generate → comply flow — with every AI path exercised
both "AI on" and "AI off / heuristic fallback".

---

## 🗂️ Project layout

```
DocForge/
├── backend/
│   ├── docforge/
│   │   ├── ai/                  # agent loop, prompts, tools, usage/pricing
│   │   ├── ai_classifier/       # template-analysis agent
│   │   ├── ai_router/           # generation agent (route + compose)
│   │   ├── compliance/          # deterministic checker + AI judge
│   │   └── ...                  # storage/, services/, api/, db/, schemas/
│   ├── tests/                   # unit + integration + api + fixtures
│   ├── alembic/                 # DB migrations (prod path)
│   └── pyproject.toml
├── frontend/                    # Next.js 14 app
│   ├── app/                     # pages: new, generate, compliance, projects, settings…
│   ├── components/              # UI + page components (icons.tsx = Lucide hub)
│   └── lib/                     # api client, types, auth context, supabase client
├── DEPLOY-VERCEL.md             # Vercel + Supabase deployment guide (current)
├── DEPLOY.md                    # Docker/Render self-host alternative
├── docker-compose.yml · Makefile · .env.example
```

---

## 🔒 Security & privacy

Per-user data isolation (owner-scoped, no-leak 404s), Supabase JWT
verification, file-type validation, upload size limits, zip-bomb &
path-traversal guards, hardened (no-DTD/no-network) XML parsing. AI keys are
bring-your-own, stored server-side only, and never returned to the client;
document text is kept out of logs; an audit trail records every AI decision
(classify/route/compliance) with its source (AI vs. heuristic) and model used.

## 📜 License

MIT.
