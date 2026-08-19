# PracticeSync AI

AI-powered practice management platform for Indian Chartered Accountants.

## Setup

### Prerequisites
- Node.js 22+ (CI builds on 22; `pnpm test` uses `node --experimental-strip-types`)
- pnpm 8+
- Python 3.11+
- pip

### Environment Variables

Each app has its own environment file — the split is a security boundary, not a
convention. `apps/web` is a static export, so anything set there is inlined into
the browser bundle and is public; every secret belongs to the backend.

```bash
cp apps/api/.env.example apps/api/.env              # all secrets live here
cp apps/web/.env.local.example apps/web/.env.local  # NEXT_PUBLIC_* only
```

### Frontend (Next.js)

```bash
cd apps/web
pnpm install
pnpm dev
```

Runs at http://localhost:3000

### Backend (FastAPI)

```bash
cd apps/api
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Runs at http://localhost:8000

### Marketing site (Next.js)

```bash
cd apps/marketing
pnpm install
pnpm dev
```

Runs at http://localhost:3001

### API Docs

FastAPI auto-generates docs at http://localhost:8000/docs

## Tests

```bash
cd apps/api && pytest tests/ -v          # backend, mock mode (no database needed)
cd apps/web && pnpm lint && pnpm test    # frontend
```

Backend tests named `test_*_pg.py` need a real Postgres and self-skip without one:

```bash
HARNESS_PG="host=127.0.0.1 port=5432 user=postgres password=postgres" \
  pytest tests/test_migrations_apply.py tests/test_*_pg.py -v
```

## Project Structure

```
caflow-ai/
├── apps/
│   ├── web/          # Next.js 14 app (static export → Cloudflare Pages)
│   ├── api/          # FastAPI backend (→ Render)
│   │   └── migrations/   # THE database migrations, applied in numeric order
│   └── marketing/    # Next.js marketing site (→ Cloudflare Pages)
├── docs/
│   └── architecture/ # authoritative subsystem design docs (01–08)
├── render.yaml       # backend deployment manifest
├── CLAUDE.md
└── README.md
```

## Test PDFs

Place test PDF files in `apps/web/public/` for the document parser.
See `apps/web/public/demo-form16.pdf` for instructions.
