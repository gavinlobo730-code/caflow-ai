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
pip install -r requirements.txt -r requirements-dev.txt   # the tests need the second file
uvicorn main:app --reload --port 8000
```

Runs at http://localhost:8000

`requirements.txt` is a **lock**: every package pinned to one version with its hash, compiled from
`requirements.in` (what you edit) on Python 3.11 for Linux. CI and the Docker image install it with
`pip install --require-hashes`; locally the flag is optional, and on macOS or Windows use Python 3.11
or the container. To change a dependency, edit `requirements.in` and recompile — the commands are at
the top of that file, and `requirements-dev.in` (pytest, never shipped in the image) is compiled
after it.

### Local stack — the backend in a container

```bash
docker compose up --build      # API at http://localhost:8000, interactive docs at /docs
```

Works from a clean clone: there is no `apps/api/.env` to create first (Docker Compose 2.24 or
later; the file is optional in `docker-compose.yml`). With none, the API starts in **mock mode** —
every router that would call Supabase sees `SUPABASE_URL` unset and answers from in-memory data —
and `APP_ENV=development` enables the dev auth fallback: a request with no JWT is treated as a
Partner of firm `firm-001`, and the `X-User-Role`, `X-Firm-Id` and `X-User-Id` headers override
that. That is enough to read the API in `/docs` and try an endpoint. Nothing persists.

What it is **not**: a local copy of the product. There is no database in it and the web app
cannot sign in against it, because sign-in is Supabase's. To run the real thing, create
`apps/api/.env` from a Supabase project's values (see `apps/api/.env.example`) — and do not copy
the example unchanged: its placeholder `SUPABASE_URL` is a value, so mock mode turns off and every
call then goes to a host that does not exist.

The web app is not in the compose file on purpose. It is a static export with no server to put in
an image, so run it on the host as above (`cd apps/web && pnpm install && pnpm dev`).

**Not built: a local Postgres with the migrations applied and the demo practice loaded.** The API
does not speak SQL — it talks to Supabase over HTTP (PostgREST for data, JWKS for auth) — so a bare
Postgres container would be a database nothing can reach. A local copy of that stack is the
Supabase CLI's `supabase start`, and this repository is not set up for it (there is no
`supabase/config.toml`; migrations live in `apps/api/migrations/` and are applied by
`apps/api/scripts/db/apply_migrations.py`). `apps/api/scripts/seed_demo_firm.py` loads the demo
practice through the API with a real user's JWT, and is a dry run until `--confirm`.

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
