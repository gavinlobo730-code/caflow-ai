# Eight granted tables with row-level security switched off

*3 September 2026. Found while reading the first guard-drift run, not by the
drift check itself — the check was blind to this direction, and now is not.*

## The finding

In a database built from the migrations in this repository, eight tables have
row-level security **disabled** and grant the `authenticated` role table
privileges:

| Table | `authenticated` holds |
|---|---|
| `credit_note_allocations` | SELECT INSERT UPDATE DELETE |
| `invoice_sequences` | SELECT INSERT UPDATE |
| `scheduler_runs` | SELECT |
| `task_dependencies` | SELECT INSERT UPDATE DELETE |
| `task_tags` | SELECT INSERT UPDATE DELETE |
| `task_templates` | SELECT |
| `task_timeline_events` | SELECT INSERT |
| `user_capacity` | SELECT INSERT UPDATE DELETE |

RLS off plus a grant means Postgres enforces nothing. `apps/web` is a static
export that reads PostgREST **directly** with the caller's JWT — roughly 320
`.from(…)` calls across ~83 tables — so on such a database any signed-in user
reads every firm's rows on all eight tables, and writes five of them.

**Production is not exposed.** It has RLS on for all eight, each with the
firm-scoped policy migration 317 now declares, applied out-of-band through
Supabase Studio. The defect is in what the migrations DECLARE, which is what
the CI template and every new environment are built from.

That is also why nothing caught it. Every assertion in this repository points
at production, or at a template built from the migrations and compared against
production for things production LACKS. A hole that exists only in the
migrations, on tables production has correctly protected, sits in the blind
spot of all of them.

## How it happened

Three steps, none of them wrong on its own.

**1. Migration 062 enabled RLS behind a guard that can silently skip.** It
covers 28 tables, each wrapped in

```sql
IF EXISTS (SELECT 1 FROM information_schema.tables
           WHERE table_schema = 'public' AND table_name = t) THEN
```

Twenty of those tables are created by migrations 063 to 069 — *after* 062
runs. On a replay the guard finds no table and skips it, with no error and no
notice. Most were rescued later by a migration that enabled RLS for its own
reasons. Six were not: `task_dependencies`, `task_tags`, `task_templates`,
`task_timeline_events`, `scheduler_runs`, `user_capacity`.
`invoice_sequences` and `credit_note_allocations` were never in 062's list.

**2. 062 stated the premise that made this survivable.** From its own header:

> These 28 tables are currently only reachable via the FastAPI backend
> (service-role key, which bypasses RLS ...). The frontend never queries them
> directly, and the `authenticated` role holds no table GRANT on any of them,
> so PostgreSQL already denies direct access before RLS is evaluated. There is
> therefore no active cross-tenant exposure today.
>
> ... should a future migration ever GRANT these tables to `authenticated`
> (e.g. a blanket GRANT ON ALL TABLES), access stays correctly firm-scoped
> instead of leaking.

**3. That future migration arrived.** `095_grant_reconciliation.sql` and
`287_itc_reversal_register_grants.sql` grant `authenticated` full DML on these
tables. The grant landed. The RLS it assumed never had.

The premise expired and nothing re-checked it. This is the interesting part:
both the migration and the drift comparison work **per table**, and a per-table
check cannot notice that a *reason* stopped being true. 062's safety argument
was a fact about a different object — the grant — recorded in a comment.

## What was done

**Migration 317** enables RLS on the eight tables and declares, for each, the
policy production already has. Both halves are no-ops in production. Each
policy is created only where one of that name is absent, so it never rewrites a
live policy. Applied twice to a clone of the migrated template to prove
idempotence, and the resulting policies hash **identically** to production's
recorded definitions for all eight — the same md5 the guard fixture stores.

Two of the eight admit a NULL `firm_id` and it matters:

* `scheduler_runs` — `jobs/scheduler.py` writes the daily sweep with no firm,
  so a policy without the NULL arm would hide every sweep row.
* `task_templates` — a NULL firm is a template shipped with the product and
  visible to every firm; a non-NULL one belongs to the firm that wrote it.

Roles are reproduced exactly as production has them: seven `TO PUBLIC`, one
`TO authenticated`. PUBLIC is the wider of the two, and converging on
`authenticated` is worth doing — but it changes who may reach rows, so it
belongs with the other thirty policies in that state rather than inside a
security fix.

**`scripts/db/guard_drift.py`** gained `rls_off_in_the_migrations`, the mirror
of the category it already had. `rls_off_in_live` asks whether production is
protected; this asks whether a new environment would be.
`test_guards_match_production_pg.py` asserts it at zero.

**`tests/test_rls_covers_every_granted_table_pg.py`** asserts the invariant
rather than the instance: *no table the `authenticated` role can reach may have
RLS off*. It needs no list to maintain. Add a table, grant it, forget the RLS,
and it fails — which is the check 062's comment should have been.

It deliberately does not assert that policies exist or are correct. RLS on with
no policy is fail-**closed** and `purchase_bill_lines` is in that state on
purpose; whether each policy scopes to the right firm is what the comparison
against production already covers.

## What is still worth doing

* **Audit the other direction of migration 062's guard.** Twenty of its tables
  were created later; this fixed the eight that stayed unprotected, but the
  same `IF EXISTS` shape appears elsewhere in the migration set and skips
  silently wherever ordering is wrong.
* **Revisit the grants themselves.** `287_itc_reversal_register_grants.sql`
  grants `authenticated` DELETE on `task_tags`, `task_dependencies` and
  `user_capacity`. Whether the frontend needs to delete those rows directly is
  a separate question from whether RLS scopes the delete; now that it does, the
  grant is safe, but it may still be wider than the product requires.
* **`purchase_bill_lines`** is RLS-on with no policy in the migrations, and has
  a policy in production. It is fail-closed, so nothing leaks, but the
  frontend's direct reads of it return nothing on a fresh deployment. It is
  part of the 77 production-only policies being declared separately.
