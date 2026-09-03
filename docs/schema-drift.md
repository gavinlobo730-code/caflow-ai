# Checking the migrations against the live database

## Why

Nothing compared the schema the migrations declare with the schema production
actually has, and the two had drifted. That gap cost real damage twice:

- **Migration 291** passed every local check and then failed against production
  with `column "status" does not exist`. `form_26as_uploads` has a different
  shape there than migration 052 declares.

- Earlier, an audit read migration 052, concluded `uploaded_by` did not exist,
  and deleted the code that wrote it. That column **does** exist in production,
  is `NOT NULL`, and has no default — so every 26AS upload failed there,
  silently, while the whole suite passed. The audit was careful. It read the
  wrong source, and no check could tell it so.

Both are one failure: the CI template is built **from** the migrations with
`--continue-on-error`, so every test and both column checkers only ever see what
the migrations say. A migration can be green here and broken there.

## Running it

Two snapshots, then a diff. Both sides use the same introspection query, so the
report shows differences in the schemas rather than differences in the question.

```bash
cd apps/api

# 1. What the migrations declare — build a scratch database from them.
python3 scripts/db/apply_migrations.py --dsn "$SCRATCH_DSN" \
    --with-compat --only-schema --continue-on-error
python3 scripts/db/schema_snapshot.py --dsn "$SCRATCH_DSN" > declared.json

# 2. What the live database has.
python3 scripts/db/schema_snapshot.py --dsn "$PRODUCTION_DSN" > live.json

# 3. Compare. Exit code 1 when anything differs, so it can gate a job.
python3 scripts/db/schema_drift.py declared.json live.json
python3 scripts/db/schema_drift.py declared.json live.json --table customers
python3 scripts/db/schema_drift.py declared.json live.json --json
```

Without a production DSN to hand, run the same query through whatever reaches
the database — the Supabase MCP `execute_sql` tool, say. `INTROSPECT_SQL` is
exported from `schema_snapshot.py` precisely so the two sides stay comparable.

## Reading the report

One category matters more than the rest:

> **`live_requires_but_migrations_do_not`** — a column the database demands,
> with no default, that the migrations do not mark required. Code written from
> the migrations omits it, and every insert is rejected in production.

That is exactly what `uploaded_by` was. Everything else is informational by
comparison: a column only the migrations know about cannot break an insert, and
a column that is *less* strict in production than in the migrations is the safe
direction.

A `NOT NULL` column **with a default** is reported under `columns_only_in_live`
rather than as the headline — the insert still succeeds, so it is drift worth
knowing about and not a live failure.

## What the first run found (31 August 2026)

191 differences. The ones that mattered:

| Category | Count |
|---|---|
| Required in live, not required by the migrations | **35** |
| Tables the migrations declare that production lacks | 7 |
| Tables in production no migration declares | 11 |
| Type differences | 17 |

**No column was `NOT NULL` with no default *and* completely absent from the
migrations** — the precise shape that broke 26AS uploads. That one was the only
one of its kind, and migration 291 fixed it.

Of the 7 tables production lacks, none is queried by live code: the only
consumers are two `_page.tsx` files, which Next.js does not route.

The 11 tables production has and no migration declares are mostly backups
(`_backup_247_*`, `_mig247_targets`) and tables from the ten migrations on
`test_migrations_apply.EXPECTED_MIGRATION_FAILURES`, which do not apply locally
but did apply to production.

## What was done about the 35

Each was traced to its insert site — 19 tables, one backend insert each, no
frontend writes. **Every one already writes every column production requires**,
including the two that spread a caller's dict (`form_26as_records` from
`parse_26as_text`, `workflow_steps` from a Pydantic model that makes the fields
mandatory). So nothing was failing.

That is luck, not safety. The hazard is the next reader: the migrations say
"nullable", so code that omits the column passes every check here and is
rejected in production. That is exactly how `form_26as_uploads.uploaded_by` was
lost. **Migration 292 declares all 35 `SET NOT NULL`**, guarded per column on
existing and currently being nullable, so it is idempotent and skips an
environment where an earlier migration never applied. In production every one is
already `NOT NULL`, so it changes the declaration and not the database.

After 292 the category is **0**, and the total is 156.

Applying it immediately caught two stale tests in
`test_gst_tds_schema_drift_pg.py` that asserted the *pre-291* insert shape for
`form_26as_uploads` — they had passed only because the column was still nullable
in the template. Both now name `uploaded_by`, matching the real code.

## Keeping it at zero

`tests/test_schema_matches_production_pg.py` compares a database built from the
migrations against `tests/fixtures/production_schema_2026-08-31.json` and fails
if any column is required in production and optional in the migrations. It runs
in the real-Postgres CI job and needs no production credentials.

It asserts **only** that one direction. The other six categories are real drift
worth knowing about, but none can reject an insert, and a test that failed on
all 156 would be turned off within a week.

The fixture is a point-in-time capture and goes stale by design — see
`apps/api/tests/fixtures/README.md` for how to refresh it.

## What is still drifted, and deliberately left alone

156 differences remain: 7 tables absent from production, 11 present only there,
32 columns the migrations declare that production lacks, 63 the reverse, 26
nullability differences in the safe direction, and 17 type differences (mostly
`uuid` vs `text` on the timeline and audit tables — those work but lose foreign
key integrity and index efficiency).

None can reject an insert. Fixing them is worthwhile and is a separate
judgement per difference; making 156 schema changes off one run is how the next
production failure gets written.

## The other half: RLS, policies and constraints (3 September 2026)

Everything above compares columns, and the docstring of `schema_drift.py` says
so: "deliberately not indexes, policies, functions or triggers". Migration 293
then found two things that diff could not see — a foreign key production
lacked, and two RESTRICTIVE policies drifted from their declared form — and the
first run of the guard diff found a CHECK constraint that had been rejecting a
real feature (`clients_status_check` without `'archived'`: archiving a client
failed in production while every test passed here).

So the column diff has a twin:

```bash
cd apps/api
python3 scripts/db/guard_snapshot.py --dsn "$SCRATCH_DSN"     > declared_guards.json
python3 scripts/db/guard_snapshot.py --dsn "$PRODUCTION_DSN"  > live_guards.json
python3 scripts/db/guard_drift.py declared_guards.json live_guards.json
```

`GUARD_SQL` is exported for the console route, exactly as `INTROSPECT_SQL` is.
Expressions are compared as an md5 — 597 policies and 1,116 constraints carry
about 150 KB of SQL, and a fixture nobody can read in a diff is a fixture
nobody checks — after folding the linter's `( SELECT auth.uid() AS uid)`
rewrite back to `auth.uid()`, which is the same predicate.

The report leads with the four directions that break something:

| Category | Why it matters |
|---|---|
| `rls_off_in_live` | every policy on the table is decoration; the frontend's direct PostgREST reads see every firm |
| `restrictive_policies_missing_from_live` | a check every row must pass is not being applied |
| `tables_left_without_a_policy_in_live` | RLS on and no policy is fail-closed: direct reads return nothing, silently |
| `check_constraints_differ` | production may REJECT a value the migrations accept — the `'archived'` failure |

`tests/test_guards_match_production_pg.py` holds all four at zero against
`tests/fixtures/production_guards_2026-09-03.json`. The first run found 276
differences in all; migration 316 closed the two live bugs and the 34
constraints production provably lacked (zero orphans, zero violators, checked
first), and `docs/audits/2026-09-03-guard-drift-first-run.md` carries the
rest — including the one UNIQUE that is NOT added, because the data is right
and the declaration is wrong.
