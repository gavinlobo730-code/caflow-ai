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

191 differences, of which the ones that matter:

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

The 35 remain. Each is a column production requires that a reader of the
migrations would think optional. Whether each is a live bug depends on whether
the code actually writes it — `form_26as_uploads.uploaded_by` was one and is
now fixed. Working through the other 34 is a separate piece of work.
