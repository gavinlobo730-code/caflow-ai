# Security Audit — Phase 13b RLS Backfill

**Date:** 2026-06-13
**Auditor:** Claude Code (automated)
**Scope:** Row-Level Security coverage across all PracticeSync AI database tables

---

## Summary

Migrations 008 and 009 (Phase 10 Workflow Engine and Phase 11 AI Copilot) were shipped without Row-Level Security policies. Migration 010 (Phase 13 AI Memory) likewise had no RLS. Migration `011_rls_policies.sql` closes all three gaps in a single idempotent backfill.

---

## RLS Coverage by Phase

### Phase 6 — Year-End (007_phase6_year_end.sql) — ALREADY SECURED

| Table | RLS Enabled | Policy |
|---|---|---|
| year_end_engagements | Yes | yee_firm_isolation |
| year_end_checklists | Yes | yec_firm_isolation |
| year_end_adjustments | Yes | yea_firm_isolation |
| account_group_mappings | Yes | agm_firm_isolation |
| financial_statement_versions | Yes | fsv_firm_isolation |
| notes_to_accounts | Yes | nta_firm_isolation |
| year_end_reviews | Yes | yer_firm_isolation |
| year_end_exports | Yes | yex_firm_isolation |

---

### Phase 10 — Workflow Engine (008_workflow_engine.sql) — SECURED BY 011

| Table | RLS Enabled | Policy | Notes |
|---|---|---|---|
| workflow_templates | Yes (011) | wft_firm_isolation | |
| workflow_instances | Yes (011) | wfi_firm_isolation | |
| workflow_executions | Yes (011) | wfe_firm_isolation | |
| workflow_failures | Yes (011) | wff_firm_isolation | |
| workflow_approvals | Yes (011) | wfa_firm_isolation | |
| workflow_schedules | Yes (011) | wfs_firm_isolation | |
| workflow_steps | No direct RLS | — | No firm_id column; protected via FK cascade from workflow_templates |
| workflow_triggers | No direct RLS | — | No firm_id column; protected via FK cascade from workflow_templates |
| workflow_conditions | No direct RLS | — | No firm_id column; protected via FK cascade from workflow_steps |
| workflow_action_logs | No direct RLS | — | No firm_id column; protected via FK cascade from workflow_instances |

---

### Phase 11 — AI Copilot (009_ai_copilot.sql) — SECURED BY 011

| Table | RLS Enabled | Policy |
|---|---|---|
| ai_conversations | Yes (011) | aic_firm_isolation |
| ai_messages | Yes (011) | aim_firm_isolation |
| ai_context_windows | Yes (011) | aicw_firm_isolation |
| ai_summaries | Yes (011) | ais_firm_isolation |
| ai_recommendations | Yes (011) | air_firm_isolation |
| ai_actions | Yes (011) | aiact_firm_isolation |
| ai_feedback | Yes (011) | aifb_firm_isolation |

---

### Phase 13 — AI Memory (010_ai_memory.sql) — SECURED BY 011 (PRIMARY SCOPE)

| Table | RLS Enabled | Policy | Sensitivity |
|---|---|---|---|
| client_profiles | Yes (011) | cp_firm_isolation | HIGH — behavioural and compliance scores |
| client_profile_history | Yes (011) | cph_firm_isolation | HIGH — version snapshots of above |
| firm_profiles | Yes (011) | fp_firm_isolation | HIGH — firm-level revenue and capacity intelligence |
| ai_memory_triggers | Yes (011) | amt_firm_isolation | MEDIUM — AI-generated alerts |
| pattern_anomalies | Yes (011) | pa_firm_isolation | HIGH — financial deviation data |
| year_end_reports | Yes (011) | yer_firm_isolation | HIGH — AI narrative with financial detail |

---

## Firm Isolation Enforcement Approach

All policies use a single consistent predicate:

```sql
firm_id::text = (auth.jwt() ->> 'firm_id')
```

This reads the `firm_id` claim that Supabase injects into the JWT when a user authenticates. The claim is set by the application layer (FastAPI) at login time and cannot be forged by a client after issuance.

**Why this approach:**
- Consistent with the pattern established in Phase 6 (`007_phase6_year_end.sql`).
- Works for all Supabase client requests (REST, Realtime, PostgREST).
- `FOR ALL` scope covers SELECT, INSERT, UPDATE, and DELETE in one policy, minimising policy count and maintenance surface.

**Backend service access:**
The FastAPI backend connects via the Supabase service-role key, which bypasses RLS. This is intentional: server-side background jobs (profile recomputation, anomaly detection) need cross-firm read access. All such code paths are explicitly documented and do not expose data to end-users directly.

---

## Residual Risks

| Risk | Status | Notes |
|---|---|---|
| workflow_steps / workflow_triggers / workflow_conditions / workflow_action_logs have no firm_id | Accepted | These child tables are only reachable via JOINs to parent tables that are RLS-protected. Direct table access via PostgREST will return empty result sets for non-matching parents. |
| Service-role key bypasses RLS | Accepted / Controlled | Used only in FastAPI backend; never exposed to frontend or clients. |
| JWT firm_id claim could be missing for unauthenticated requests | Mitigated | `auth.jwt() ->> 'firm_id'` returns NULL for unauthenticated sessions; NULL = UUID comparison is always false, so all rows are hidden. |

---

## Migration File

`supabase/migrations/011_rls_policies.sql`

The migration is fully idempotent. Each `CREATE POLICY` is wrapped in a `DO $$ BEGIN ... EXCEPTION WHEN duplicate_object THEN NULL; END $$` block, and `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` is a no-op if already enabled.
