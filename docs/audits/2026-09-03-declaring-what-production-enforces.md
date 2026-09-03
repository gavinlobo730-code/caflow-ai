# Declaring the guards production enforces

*3 September 2026. Migration 319, the last step of the guard-drift first run.*

## What it does

Declares, in the migrations, 59 constraints and 52 policies that existed only in
the live database. Combined with 317 (row-level security on eight granted
tables) and 318 (two status vocabularies), this takes
`constraints_only_in_live` from **62 to 0** and `policies_only_in_live` from
**77 to 22**, where the 22 are excluded on purpose.

In production every statement is a no-op, guarded on its own existence.
Everywhere else — the CI template that every test runs against, and any new
environment — they start enforcing what production has always enforced.

## Why the direction matters

This is the "migration 292 pattern", and it is not bookkeeping. Reading the
first run of the comparison turned up three writes the shipped code makes that
production **refuses**, each breaking a feature for a real user while every test
passed:

* a client-portal document upload rejected by a foreign key,
* a GST sync status outside its CHECK, and
* a Tally job status outside its CHECK.

All three were invisible here precisely because the template had none of those
constraints. Declaring them is what makes the next one fail in CI instead.

## How each was verified

The survey ran one agent per table for the constraints and one per group of
tables for the policies — 28 in all. Each probed a throwaway clone of the
migrated template rather than reasoning about the statement, and for a CHECK
also searched the repository for values the constraint would reject.

The decisive check came after: every one of the 111 declared objects was
compared against production's recorded definition by hash. **All 111 match** —
the same md5 over `pg_get_constraintdef` / the policy expression that the guard
fixture stores. A declaration that drifted from what production runs would have
shown up here, and none did.

Migration 319 was applied twice to a clone to prove it is idempotent.

## The 15 RESTRICTIVE policies are the important half

A RESTRICTIVE policy is a check **every** row must pass, so its absence widens
what a caller can reach — unlike a permissive one, which only grants. Fifteen of
them, the `*_assignment_scope` family from migrations 260/261, existed only in
production. A fresh deployment had no assignment scoping on those tables at all.

## What is deliberately NOT declared

Declaring "what production has" is not uniformly right, because some of what
production has is stale. Twenty-two policies are left out, in four groups.

**Eight `firm_iso_wf_*` policies** on the workflow tables. Their predicate is
`firm_id = current_setting('app.current_firm_id', true)::uuid`. That setting
appears **nowhere in this repository** — nothing sets it, so the policy admits
nothing — while the migrations already declare `firm_isolation` on the same
tables using the current helper `get_my_firm_id()`. Copying the legacy
mechanism into the migrations would entrench a superseded one.

**Seven `firm_iso_*` policies** on the `ai_*` tables, for the same reason: each
table already carries a declared `*_firm_isolation` policy with the current
predicate, and a second permissive policy is OR'd with the first.

**`audit_log_own_firm`.** The migrations declare `audit_log_partner_read`;
production's policy lets the whole firm read the audit log. That is a change to
who can read, in the widening direction, and belongs to whoever owns the audit
trail rather than to a mechanical sweep.

**Six policies** on `purchase_bills`, `receipts`, `receipt_allocations`,
`credit_notes`, `credit_note_lines` and `client_sales_invoice_lines`. Migration
053 explicitly DROPPED these names and replaced them with
`firm_client_isolation`, which additionally requires the client to belong to the
firm. **Production still runs the older, weaker ones.** The right direction here
is to bring production UP to the stricter policy, not to copy the weaker one
down — which is the mirror image of everything else in this migration, and is
recorded as its own task.

Also unchanged: `client_profiles_firm_id_client_id_key`, where production
violates the declaration on purpose because profiles are versioned, so the
declaration is what is wrong.

## One test fixture had to change

`tests/test_gst_tds_schema_drift_pg.py` seeded only `firms` and `clients`, and
put the FIRM uuid into `form_26as_uploads.uploaded_by` — a column that foreign
keys `public.users(id)`. It passed only while the constraint was undeclared. The
fixture now seeds a real user and uses its id.

That is the intended consequence of this work, and worth naming: declaring a
constraint makes tests that were quietly writing impossible data start failing.
One did.

## What is left

`policies_missing_from_live` (19) and `constraints_missing_from_live` (36) are
the mirror direction — things the migrations declare and production lacks. Most
are the objects migrations 316 to 319 are adding, which the fixture predates;
the guards fixture should be refreshed once 319 has applied, at which point both
numbers should drop sharply and what remains will be genuine.

`policies_differ` (30, production stricter with `TO authenticated`),
`constraints_differ` (29, all `ON DELETE` behaviour) and the seven tables
production lacks are unchanged and remain recorded in the first-run audit.
