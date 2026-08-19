# Migrations have moved

All database migrations live in a single authoritative directory:

    apps/api/migrations/

They are numbered sequentially from 001 (`NNN_name.sql`) and **must be applied
in strict numeric order**. Do not add migrations here.

(The previous version of this note pinned the range as "001 through 071". Don't
restore a number that has to be maintained by hand — `ls apps/api/migrations/`
answers it, and being wrong here is worse than being silent.)

`supabase/migrations/` is the Supabase CLI's conventional location, so it is the
first place anyone looks — which is the only reason this note still exists. The
project is not set up for the CLI at all (there is no `supabase/config.toml`),
and the CLI is not how schema changes are applied here.

## How migrations actually reach the database

`apps/api/scripts/db/apply_migrations.py` applies anything not already recorded
in production's `schema_migrations` table — idempotent, ordered, fails fast on
the first error.

It runs automatically: the `apply pending migrations — production` job in
`.github/workflows/backend-ci.yml` executes it against the live Supabase project
on every push to `main`, once the tests and the migration-apply ratchet pass.
**Merging a migration to `main` applies it to production**, with no manual step
in between. See `docs/deploy-migrations.md`.

`apps/api/core/schema_guard.py` is the boot-time backstop for the case where
code and schema still drift apart.

## History

This directory previously held a "Phase 10-13 overlay" set numbered 001-011
that collided with the core schema's own 001-011. Those files were consolidated
into `apps/api/migrations/` on branch `claude/phase-13b-production-hardening`:

| old (supabase/migrations)      | new (apps/api/migrations)        |
|--------------------------------|----------------------------------|
| 001_phase12_tasks.sql          | 063_phase12_tasks.sql            |
| 002_phase12_time.sql           | 064_phase12_time.sql             |
| 003_phase12_notifications.sql  | 065_phase12_notifications.sql    |
| 004_assignment_rules.sql       | DROPPED — duplicate of 045_assignment_rules.sql |
| 005_escalation_rules.sql       | DROPPED — duplicate of 046_escalation_rules.sql |
| 006_phase12_completion.sql     | 066_phase12_completion.sql       |
| 007_phase6_year_end.sql        | 067_phase6_year_end.sql          |
| 008_workflow_engine.sql        | 068_workflow_engine.sql          |
| 009_ai_copilot.sql             | 069_ai_copilot.sql               |
| 010_ai_memory.sql              | 070_ai_memory.sql                |
| 011_rls_policies.sql           | 071_rls_policies.sql             |

The two dropped files defined `assignment_rules` / `escalation_rules` tables that
already exist in the core schema (045/046) with identical structure and idempotent
`CREATE TABLE IF NOT EXISTS` guards, so they were redundant.
