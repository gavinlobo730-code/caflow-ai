PracticeSync — AI-powered practice management platform for Indian Chartered Accountants.
Replaces Tally + ClearTax + Winman + WhatsApp with one unified AI-first platform.

Naming: the product is **PracticeSync**. The repo, the Supabase project, log prefixes
(`caflow.*`), some seed data and a few mock URLs still say `caflow` / `CAflow AI`. That
is known cosmetic legacy — do not "tidy" it opportunistically. It appears in import
paths, env keys and migration history, and a careless rename breaks all three.

## Repo layout

Three apps, not two:

- `apps/api` — FastAPI (Python 3.11). **All** business logic lives here.
- `apps/web` — Next.js 14, the product. Static export (`output: "export"` in
  `next.config.mjs`), deployed to Cloudflare Pages.
- `apps/marketing` — separate Next.js marketing site, its own Cloudflare Pages project.

## Tech stack

- Frontend: Next.js 14, TypeScript, Tailwind CSS, shadcn/ui primitives in
  `apps/web/components/ui/` (vendored source — there is no `components.json`, so the
  shadcn CLI will not work; add primitives by hand).
- Backend: FastAPI (Python 3.11)
- Database: Supabase (Postgres), project region ap-south-1 (Mumbai)
- Package manager: pnpm for frontend, pip for backend

### AI providers — every key is backend-only

`apps/web` builds as a static export, so it has no server and can read nothing but
`NEXT_PUBLIC_*` values, which are inlined into the browser bundle. An AI key in the
frontend environment is at best ignored and at worst published. All AI calls happen in
`apps/api`, with keys in `apps/api/.env` ONLY.

- **Groq** — chat/text features and PDF (text-only) invoice extraction. Needs
  `GROQ_API_KEY`. Default model `llama-3.3-70b-versatile`, overridable via
  `GROQ_TEXT_MODEL`.
- **Gemini** — image-based invoice extraction only (photographed/scanned bills, in
  `routers/document_intelligence_v1.py`). Needs `GEMINI_API_KEY`. Default model
  `gemini-3.5-flash`, overridable via `GEMINI_VISION_MODEL`.

Why two providers: Groq's vision models returned a live 404 `model_not_found` on this
account; Gemini's free tier is multimodal-native and already provisioned. The PDF/text
path stayed on Groq and works fine. Treat the model names above as current defaults,
not as contracts — `gemini-2.5-flash` was retired by Google ahead of its announced
shutdown, and the code reads the env var precisely so the next retirement is a config
change. The code is the authority; keep this file in step with it.

## Money and the general ledger

- **Every rupee calculation uses integer paise arithmetic, never floating point.**
  Monetary columns are `*_paise BIGINT`. ₹1 = 100 paise.
- **One posting kernel, no alternative paths.** Every accounting event that touches the
  GL is written by `services/phase2_journal_service._create_journal`. It asserts
  double-entry balance and dedupes on `(client_id, reference_no, entry_date)` before
  inserting. Sales, purchases, receipts, payments, credit/debit notes, banking, payroll,
  fixed assets, opening balances, manual journals and reversals all route through it. Do
  not add a second write path.
- The live GL is `journal_entries` + `journal_lines` only. A posted entry can never be
  hard-DELETEd or rewritten in place (DB triggers), and a correction to a real
  transaction is an append-only reversal. But immutability is not absolute, and the
  code is the authority on where the line falls: a **manual** entry may be edited
  (migration 266) or soft-deleted (275, 276) while its period is open, judged by
  `journal_period_lock_reason` — the CA locks the year, or a return covering the date is
  filed. Migration 276 also lets a reversed entry and its reversal go together, since a
  pair strands nothing and nets to zero. This tracks Indian law rather than exceeding it:
  the proviso to Rule 3(1) of the Companies (Accounts) Rules 2014 requires an **edit
  log**, which presumes entries can change, and TallyPrime's Edit Log — mandatory and
  non-disableable — still lets a voucher be deleted. The log is what is immutable, not
  the entry. Every deletion writes the whole entry, its lines and their account names to
  `audit_log` in the same transaction, unswallowed.
- `created_by` / `posted_by` FK to `public.users.id` (the internal user id), **not** the
  Supabase auth id.
- Money crosses the API as raw integer `*_paise`. The frontend formats to ₹. Rupee
  conversion happens only at the statutory payload boundary — see
  `domain/gst/money.py`: 2-decimal rupees for GSTR-1, whole rupees for GSTR-3B
  (CGST Act §170, half rounded up).

## Indian tax domain rules — never violate these

- GSTIN format: 2-digit state code + PAN (10 chars) + 1 digit entity number + Z + 1 check digit
- PAN format: AAAAA9999A (5 uppercase letters + 4 digits + 1 uppercase letter)
- Financial year: April 1 to March 31
- GSTR-1 due date: 11th of the following month
- GSTR-3B due date: 20th of the following month
- GSTR-9 (annual): 31st December
- TDS return (24Q/26Q): Q1 31 Jul, Q2 31 Oct, Q3 31 Jan, Q4 31 May. Q4 is the exception — it is NOT the end of the month following quarter end (that would be 30 Apr). services/compliance_engine.py::tds_return_due_date is the authority; keep any prose in step with it.
- Advance tax due dates: 15 Jun (15%), 15 Sep (45%), 15 Dec (75%), 15 Mar (100%)
- ITR (IT Act §139): 31 July, or 31 October where audit applies
- MCA/ROC offsets from the AGM date: ADT-1 +15d (§139), AOC-4 +30d (§137), MGT-7 +60d (§92)
- **Correction window** (CGST §37(3), §39(9), §16(4)): 30 November following the FY, **or
  the date GSTR-9 was furnished, whichever is EARLIER**. Filing the annual return early
  shuts the window early. `compliance_engine.correction_window_closes()` is the function
  to use — `november_30_cutoff()` is only the statutory outer limit and will tell a CA a
  correction is available when it is not.
- Never auto-submit anything to any government portal — always require explicit CA confirmation click

`services/compliance_engine.py` is the single source for every due date above. If prose
and that module disagree, the module wins and the prose gets fixed.

## Code rules — always follow

- Never hardcode API keys — always use .env files
- Every financial calculation must have a corresponding unit test
- All GST/ITR logic must have a comment citing the relevant section of the CGST Act or IT Act
- Before any government API call, add comment: # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
- Zero business logic in the frontend. Computation, validation and statutory rules live
  in `apps/api`. (This is about logic, not about data access — see below.)
- All API responses must follow: { success: bool, data: any, error: string | null }
  (`models/common.api_response`)

## The frontend's second data path

The frontend does **not** reach the database only through FastAPI. Roughly 320
`.from("…").select(…)` calls across ~100 files read and write ~83 tables directly via
PostgREST. That is why:

- `rbac()` never runs on those calls — the only access check is RLS. Role-aware write
  policies (migrations 260/261) exist for exactly this, and
  `tests/test_direct_write_tables_are_role_guarded.py` tracks which tables are still
  unguarded.
- **Renaming or dropping a column can break the frontend while backend CI stays green.**
  `tests/test_frontend_columns_exist_pg.py` parses those select lists and checks them
  against the real schema. Run it when you touch a migration.

## Tenancy and access

- `firm` is the tenant, `client` is the accounting entity. Every row carries `firm_id`;
  every report and filing is client-scoped.
- The service-role key **bypasses RLS**, so the app-layer `.eq("firm_id", …)` filter is
  the primary isolation control, with firm-scoped RLS policies as defence in depth.
  Never write a query that omits it.
- With `USE_USER_JWT` on, requests run as `authenticated` (anon key + caller's JWT) and
  RLS is genuinely enforced on the API path too.
- RBAC: `Partner > Manager > Executive > Reviewer > Client`
  (`core/permissions.py`, applied as `rbac(resource, action)`).

## Tests

Backend, from `apps/api`:

```
pytest tests/ -v                      # the mock-mode suite (~7,000 tests, no DB needed)
pytest tests/test_foo.py -v           # one module
```

Real-Postgres tests are named `test_*_pg.py` (plus `test_migrations_apply.py`). They
self-skip unless `HARNESS_PG` is set and `psql` is on PATH:

```
HARNESS_PG="host=127.0.0.1 port=5432 user=postgres password=postgres" \
  pytest tests/test_migrations_apply.py tests/test_*_pg.py -v
```

Frontend, from `apps/web`: `pnpm lint`, `pnpm exec tsc --noEmit`, `pnpm test`,
`pnpm build`.

## CI

Two **required** status checks on `main`, both in `.github/workflows/backend-ci.yml`:

- `pytest — mock mode (Python 3.11)`
- `migration apply — real Postgres 16`

Never add a `paths:` filter to the `on:` block of a workflow carrying a required check.
A path-filtered workflow does not run when the filter misses, the check never reports,
and GitHub treats that as pending forever — which makes unrelated PRs unmergeable with
no failing check to point at. Filter inside, in the `scope` job, as these workflows do.

## Migrations

- `apps/api/migrations/NNN_name.sql`, sequentially numbered from 001. Check
  `ls apps/api/migrations/` for the next free number rather than trusting a
  figure written down anywhere — including here.
- **Merging a migration to `main` applies it to the production database.** The
  `apply pending migrations — production` job runs `scripts/db/apply_migrations.py`
  against the live Supabase project on every push to `main`, once tests and the
  migration ratchet pass. There is no manual review step in between. See
  `docs/deploy-migrations.md`.
- `core/schema_guard.py` is the boot-time backstop: it surfaces code/schema drift loudly
  instead of letting writes fail silently behind broad `try/except`.

## Deployment

- API → Render, Docker, **Singapore region**. It must stay near the Mumbai Supabase; the
  reasoning and the measurements are in `render.yaml` and Render cannot move a service
  between regions.
- `apps/web` and `apps/marketing` → two separate Cloudflare Pages projects.
- `render.yaml` must declare every environment variable the backend reads —
  `tests/test_render_manifest_matches_code.py` enforces this in both directions
  (nothing read-but-undeclared, nothing declared-but-unread).
- The daily job sweep is in-process APScheduler (`jobs/scheduler.py`), gated on
  `ENABLE_SCHEDULER`, enabled in exactly one process. On Render's free tier the instance
  sleeps, so `.github/workflows/wake-before-scheduler.yml` pings `/health` across the
  window to keep it alive; the sweep also catches up on jobs whose trigger was slept
  through.

## Where the design is written down

`docs/architecture/01-08` is the authoritative design set — accounting engine, posting
kernel, financial years, opening balances, manual journals, multi-currency, GST engine,
reporting engine. Read the relevant one before changing a subsystem. `docs/audits/` and
the batch completion reports are historical records, not current specs.

## Scope

Well past MVP. Shipped and mounted: accounting/GL, GST (GSTR-1/3B/9, 2A/2B recon,
amendments, ITC reversal), TDS, income tax/ITR, payroll, banking and reconciliation,
fixed assets, inventory, year-end and Schedule III, client and employee portals,
relationship/health/lifecycle intelligence, AI copilot and memory, workflow automation,
Tally migration, and prepare-only e-invoice/e-way/XBRL rails.

Don't infer scope from this list — ask. It is a description of what exists, not a
licence to extend any of it.

## Reporting times to the user

- Always state times in IST (UTC + 5:30), never UTC. This applies to everything you tell the user — CI timings, when a job ran, when a check-in fires, timestamps read out of the database. Convert before reporting; don't make the user do the arithmetic.
- This is a PRESENTATION rule only. It does not change what is stored or scheduled: `timestamptz` columns (e.g. `scheduler_runs.started_at`) are UTC on disk, and GitHub Actions cron expressions — including the daily-sweep schedule in .github/workflows/ and any `create_trigger` cron — are evaluated in UTC. Both are correct; rewriting either to "look like IST" would move when jobs actually run.
- So: convert at the point of reporting. When you show a raw query result or edit a cron line, say which zone that value is in, since the stored value stays UTC.
- Worked example: the daily sweep is nominally 06:00 IST = 00:30 UTC. A run recorded as `2026-08-18 01:36+00` is reported as "07:06 IST" — and that hour of drift is GitHub cron lateness under load, which is what the catch-up in jobs/ exists to absorb.

## Bug fixing

- When the user reports a bug, don't just patch the one instance. Identify the underlying pattern (wrong column name, missing null check, stale label, unapplied migration, etc.) and grep/search the rest of the codebase for the same pattern before calling the fix done. Report what else was found, even if you decide not to touch it.

## Commit messages

Match the existing history. A commit explains **what was wrong**, **what the fix does and
why that shape**, and **how it was verified** — including how many new tests fail against
the previous code (the negative control). State when a change has no live effect yet, and
say so explicitly when there is no migration. Subject line is a plain sentence describing
the behaviour change, not a conventional-commits prefix.
