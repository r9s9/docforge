# DocForge

**AI-powered DOCX reverse-engineering and document assembly platform.**

DocForge takes 1–5 *filled* example Word documents of the same type, figures out
what content is **fixed** vs **dynamic** vs **repeatable** vs **auto**, and turns
them into a reusable, layout-preserving **template** plus structured intelligence.
You can then generate new documents from structured data *or* from unstructured
notes (the AI routes the content to the right fields), with validation and a
review step before anything is finalized.

It is **local-first and privacy-aware**: with no API key configured it runs a
fully deterministic heuristic engine — no external calls. Point it at OpenAI or
any OpenAI-compatible local server (Ollama, LM Studio, vLLM…) to enable the LLM.

---

## Highlights

- **Reverse-engineer templates from real examples** — upload filled DOCX files;
  DocForge diffs them, classifies every element, and builds a clean
  `template.docx` with Jinja placeholders, preserving company formatting by
  modifying the original OOXML in place (never rebuilding from scratch).
- **Two generation modes** — structured JSON/form, or unstructured text that the
  AI router maps onto template fields (with missing/ambiguous detection).
- **Deterministic assembly** — AI decides *what goes where*; a deterministic
  engine (`docxtpl` + an lxml OOXML fallback) does the rendering.
- **Validation** — required fields, types, dates, numbers, enums, table schema,
  regex; human-readable report with suggested fixes.
- **Versioned template packages** on disk, an audit trail of AI decisions, and a
  clean REST API.
- **Claude-styled Next.js web app** for upload → review → publish → generate.

---

## Architecture

```
┌─────────────┐   examples   ┌──────────────────────────────────────────────┐
│  Next.js UI │ ───────────► │                FastAPI backend                 │
│ (frontend/) │ ◄─────────── │                 (backend/)                     │
└─────────────┘   JSON/REST  │                                                │
                             │  document_ingest → ooxml_extractor →           │
                             │  structure_normalizer → multi_doc_differ →     │
                             │  ai_classifier → template_builder →            │
                             │  template_registry  (publish)                  │
                             │                                                │
                             │  ai_router → assembler → validator  (generate) │
                             └──────────────────────────────────────────────┘
```

AI is used for exactly three tasks (each with a deterministic fallback):
**classify elements**, **understand sections**, **route unstructured content**.
Everything else is deterministic and unit-tested.

Backend modules (`backend/docforge/`):

| Module | Responsibility |
|---|---|
| `document_ingest` | Upload validation, safe storage, zip-bomb/XXE guards |
| `ooxml_extractor` | Defensive OPC/zip reading, parts, rels, media, numbering |
| `structure_normalizer` | Normalized element tree with stable node IDs + xpaths |
| `multi_doc_differ` | Structural alignment + confidence-scored diffs |
| `ai_classifier` | FIXED/DYNAMIC/REPEATABLE/AUTO classification + fields/rules |
| `template_builder` | Build `template.docx` (docxtpl + lxml OOXML fallback) |
| `template_registry` | Versioned template package storage |
| `ai_router` | Map structured/unstructured input to fields |
| `assembler` | Deterministic DOCX rendering |
| `validator` | Rule engine + human-readable report |
| `api` | REST endpoints + background jobs |
| `services/` | Orchestration: analyze, publish, generate, seed, audit |

---

## Tech stack

- **Backend:** Python 3.11+, FastAPI, SQLAlchemy 2 (SQLite by default), Pydantic v2,
  python-docx, docxtpl, lxml.
- **Frontend:** Next.js 14 (App Router) + React 18 + TypeScript.
- **AI:** OpenAI-compatible HTTP client (optional).

---

## Quickstart (local dev)

### 1. Backend

```bash
cd backend
python -m venv .venv
# Windows:  .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"

cp ../.env.example .env          # optional; sensible defaults work out of the box
docforge seed                     # build 3 demo templates (optional)
docforge serve                    # API on http://localhost:8000  (docs at /docs)
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev                       # web app on http://localhost:3000
```

The Next dev server proxies `/api` to `http://localhost:8000` (see
`next.config.mjs`). Open **http://localhost:3000**.

> No API key needed — DocForge runs the deterministic heuristic engine offline.
> To enable an LLM, set `DOCFORGE_AI_ENABLED=true` and the AI vars in `.env`.

---

## Run with Docker

```bash
docker compose up --build
```

- Backend API + built frontend served at **http://localhost:8000**
- Data persists in the `docforge-data` volume.

(For active frontend development prefer `npm run dev`; Docker serves a production
build of the SPA from the backend.)

---

## Deploying the frontend to Vercel / Next.js

The frontend is a standard Next.js app and deploys to Vercel (or any Next host)
independently of the backend:

1. Push the repo to GitHub and import `frontend/` as a Vercel project
   (root directory = `frontend`).
2. Set an environment variable so the browser calls your deployed backend:
   - `NEXT_PUBLIC_API_BASE_URL=https://your-backend.example.com`
3. Deploy. (Without that var, the app calls same-origin `/api`, which works when
   you self-host the Next server with `BACKEND_URL` set to the backend.)

Host the backend anywhere that runs Python (Fly.io, Render, a VM, the provided
Docker image). Ensure CORS allows your frontend origin (configurable in
`backend/docforge/api/app.py`).

---

## Configuration

All settings are environment variables prefixed `DOCFORGE_` (see `.env.example`).
Key ones:

| Variable | Default | Purpose |
|---|---|---|
| `DOCFORGE_DATA_DIR` | `./data` | uploads, templates, generated docs |
| `DOCFORGE_DATABASE_URL` | `sqlite:///./data/docforge.db` | DB connection |
| `DOCFORGE_AI_ENABLED` | `false` | enable the LLM (else heuristic) |
| `DOCFORGE_AI_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible endpoint |
| `DOCFORGE_AI_API_KEY` | — | secret, env only, never logged |
| `DOCFORGE_AI_MODEL` | `gpt-4o-mini` | model name |
| `DOCFORGE_MAX_UPLOAD_MB` | `25` | per-file upload limit |

---

## API (selected)

| Method & path | Purpose |
|---|---|
| `POST /api/templates/analyze` | upload 1–5 DOCX → analysis (review) job |
| `POST /api/templates` | publish a reviewed job into a template version |
| `GET  /api/templates` | list templates |
| `GET  /api/templates/{id}` | template detail (latest fields/rules/manifest) |
| `GET  /api/templates/{id}/versions[/{v}]` | version browser |
| `POST /api/templates/{id}/generate` | generate a DOCX |
| `POST /api/templates/{id}/route` | preview content routing (no generation) |
| `POST /api/templates/{id}/validate` | validate a context |
| `GET  /api/generations/{id}[/download]` | generation status / download DOCX |
| `GET  /api/health` | health + AI status |

Interactive docs: **http://localhost:8000/docs**.

---

## Testing

```bash
cd backend
pytest                 # unit + integration + API tests
ruff check docforge    # lint
```

Fixtures generate three pairs of similar documents (project report, invoice,
compliance report) deterministically — see `docforge/sampledata.py`.

---

## Project layout

```
DocForge/
├── backend/
│   ├── docforge/            # the platform (modules above)
│   ├── tests/               # unit + integration + api + fixtures
│   ├── alembic/             # DB migrations (enterprise path)
│   └── pyproject.toml
├── frontend/                # Next.js 14 web app (Claude-styled)
│   ├── app/                 # App Router pages
│   ├── components/          # UI + page components
│   └── lib/                 # api client + types
├── docker-compose.yml
├── Makefile
└── .env.example
```

---

## Security & privacy

File-type validation, upload size limits, zip-bomb & path-traversal guards,
hardened (no-DTD/no-network) XML parsing, secrets from env only, document text
kept out of logs, and an audit trail for AI decisions and template publication.
See spec §19.

## License

MIT.
