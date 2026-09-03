# The memory pipeline could not run on any database built from the migrations

*3 September 2026. Migration 320. Found while acting on the guard-drift
follow-up that was filed as "swap a unique constraint".*

## The finding

`public.client_profiles` has **9 columns** in a database built from these
migrations and **29** in production. The twenty missing ones are the entire
versioned profile the memory pipeline computes: `profile_version`,
`is_current`, `last_computed_at`, `data_points_used`, and every behavioural,
compliance and financial field.

`public.client_profile_history` did not exist in the migrations at all.

So on the CI template, and on any new environment, the whole memory and
client-intelligence subsystem cannot run. Every write from
`repositories/memory_repository.upsert_profile` fails with *column does not
exist*, and its history snapshot has nowhere to go.

Production is fine, and always was. The defect is entirely in what the
migrations declare.

## How it happened — the same silent no-op, a third time

Migration 059 creates `client_profiles` with nine columns and a
`UNIQUE (firm_id, client_id)`. Migration 070 then creates it again, properly,
with all twenty-nine — as `CREATE TABLE IF NOT EXISTS`, which finds 059's table
and does nothing. 070 later references a column that `CREATE` never made and
fails, which is why it sits in `EXPECTED_MIGRATION_FAILURES` with the note
*"client_profiles CREATE IF NOT EXISTS no-ops (059) -> is_current missing"*.

The note was right and had been there for months. What nobody drew from it is
that the table therefore has 059's shape everywhere except production.

This is the third instance of one pattern in this series:

| Migration | Guarded statement | What it silently skipped |
|---|---|---|
| 062 | `IF EXISTS (… information_schema.tables …)` | row-level security on 8 tables (fixed by 317) |
| 068 | `CREATE TABLE IF NOT EXISTS workflow_steps` | `template_id` |
| 070 | `CREATE TABLE IF NOT EXISTS client_profiles` | 20 columns and the history table |

The guard is not the problem — idempotence is right. Doing nothing *quietly*
when the guard is already satisfied is.

## Why no check caught it

Two near-misses, and both are worth recording because each looked like it was
covering this.

**`test_schema_matches_production_pg.py`** asserts the directions that reject an
insert *in production*: a column production requires and the migrations call
optional, and a column the migrations declare that production lacks. This is
the mirror — columns production has and the migrations lack — which its
docstring calls informational, on the grounds that it "cannot break an insert".
That is true of production and false of everywhere else. Here it breaks every
insert on a fresh database.

**`test_backend_columns_exist_pg.py`** reads column names as text out of
`.table("…").insert({…})` calls, and should have seen all twenty. It could not:
`upsert_profile` built its payload in a variable and called `.insert(record)`,
so every name was an "unreadable reference" in that check's own accounting —
the blind spot it already budgets for. The payload is now written inline, the
same fix the bank column-mapping service took for the same reason, so those
columns are permanently checked.

## The unique, which is the part that was a decision

Migration 059 declares `UNIQUE (firm_id, client_id)`. Production does not have
it and **cannot**: `upsert_profile` versions profiles — it retires the current
row (`is_current = false`), inserts the next with `profile_version + 1`, and
writes a `client_profile_history` snapshot pointing at the retired one.
Production holds 100 rows across 6 client pairs, one per client per day since
18 August.

So the declaration was never right. What the code actually guarantees is **one
current profile per client**, and that is what migration 320 declares instead,
as a partial unique index. Checked against production first: 6 groups, every one
with exactly one `is_current` row, none with two, none with zero.

It is safe against the write path because the order is retire-then-insert. Were
it ever reordered to insert-then-retire, the index would reject the insert —
which is worth knowing before anyone changes it, and is why the migration says
so.

## Not decided

A profile recomputed daily keeps every version for ever: six clients produced
100 rows in sixteen days. Whether that wants a retention rule is a product
question about the memory pipeline, recorded here rather than answered.

## Verification

* Both tables now match production **column for column, type for type,
  nullability for nullability**, compared against the production schema
  snapshot.
* Migration 320 applied twice to a clone of the migrated template.
* `client_profile_history` is created with the grants and the two policies
  production has, including the RESTRICTIVE `*_assignment_scope` one — a new
  table with row-level security off would have re-created exactly the hole
  migration 317 had just repaired for eight other tables.
