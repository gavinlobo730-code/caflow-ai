# Migrations have moved

All database migrations now live in a single authoritative directory:

    apps/api/migrations/

They are numbered sequentially (001 through 071) and **must be applied in
strict numeric order**. Do not add migrations here.

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
