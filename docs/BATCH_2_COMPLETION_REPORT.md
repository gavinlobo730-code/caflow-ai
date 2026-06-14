# Batch 2 Completion Report — Firm-as-Internal-Client Provisioning + Guardrails G1–G4

**Amendment v1.1 (Phase 10B) · Batch 2 of 7**
**Date:** 2026-06-14 · **Branch:** `claude/compassionate-darwin-nffpnb`
**Migration:** `074_internal_client_rls_guardrails.sql` (+ `_rollback.sql`)

## 0. Key architectural finding (drives the design)

The backend connects with the Supabase **SERVICE_ROLE key, which BYPASSES RLS**
(`core/supabase_client.py`: *"bypasses RLS … tenant isolation enforced at
repository level"*). Therefore guardrails are enforced in **two layers**:

1. **Application layer (Python repo/API) — the *effective* control for the app.**
2. **RLS restrictive policies (migration 074) — defence-in-depth** for any direct
   / non-service-role / PostgREST / anon+JWT database access.

Both layers were implemented and tested.

## 1. Audit of affected code paths

`clients` is reached two ways: ~14 call sites via `client_repo.find_all` (fixed
centrally) and a handful of **direct** `db.table("clients")` queries (patched
individually). Single-client financial lookups (e.g. `sales_invoices.py:252`,
`purchase_bills.py:173`) were deliberately **left untouched** — the internal
client legitimately owns its own books. Full inventory in the commit; the
exclusion sites actually changed are listed in §3.

## 2. Guardrails implemented

| Guardrail | Mechanism |
|---|---|
| **G1 Partner-only access** | (a) `clients` workspace endpoint calls `assert_can_view_client` → 404 for non-partners on the internal row; (b) **RLS restrictive** `clients_internal_partner_only` + per-table `*_internal_partner_only` on all client-scoped financial tables (`USING/WITH CHECK get_my_role()='Partner' OR client_id IS DISTINCT FROM my_internal_client_id()`). Partner = Owner-equivalent. |
| **G2 Exclusion from populations** | `client_repo.find_all`/`count` exclude `is_internal` **by default** (`include_internal=True` opt-in for partner surfaces) → fixes ~14 aggregations at once; plus direct-query patches in Health (recalc + per-client guard), Analytics (client + firm KPIs), Onboarding status. `clients_external` view (Batch 1) remains the SQL single-source. |
| **G3 Single customer link** | `client_firm_customer_links UNIQUE(firm_id, client_id)` (Batch 1) structurally guarantees one link per practice client. The link **write-path** lands in Batch 3 (billing). |
| **G4 Module cap** | `assert_not_internal_for_payroll` blocks the internal client on all payroll **write** endpoints (employees, salary-structures, runs); RLS restrictive policies also cover payroll tables (defence-in-depth). Accounting/GST/TDS/documents/reports/billing remain available. |

## 3. Files changed

**New**
- `services/internal_client_service.py` — `is_partner`, `get_internal_client_id`, `is_internal_client`, `assert_can_view_client` (G1), `assert_partner_for_internal_id` (G1), `assert_not_internal_for_payroll` (G4), idempotent `provision(...)`.
- `routers/practice.py` — Partner-only `GET /api/practice`, `POST /api/practice/provision` (idempotent provisioning for new + existing firms).
- `migrations/074_internal_client_rls_guardrails.sql` (+ rollback) — `my_internal_client_id()` helper, restrictive policy on `clients`, and a DO-loop applying restrictive policies to every listed client-scoped financial table that exists.
- Tests: `tests/test_batch2_internal_client.py` (G1/G2/G4 unit, mock mode), `tests/test_batch2_guardrails_migration.py` + `tests/sql/batch2_guardrails_verify.sql` (RLS, real PG).

**Modified**
- `repositories/client_repository.py` — `find_all`/`count` exclude internal by default (G2).
- `routers/clients.py` — G1 guard on the client workspace.
- `routers/health.py` — recalc excludes internal; per-client calc blocks internal (G2).
- `routers/analytics.py` — client + firm KPIs exclude internal (G2).
- `routers/onboarding.py` — status count excludes internal; **provisioning hook** in `create_firm` (idempotent, non-fatal) + optional `entity_type`.
- `routers/payroll.py` — G4 guards on the 3 write endpoints.
- `core/permissions.py` — new Partner-only `practice` resource.
- `main.py` — register practice router.

## 4. Test results

- **RLS (real PostgreSQL 16, `test_batch2_guardrails_migration.py`):** staff cannot
  see the internal client row, its journals, or its sales invoices; staff **write**
  to internal books is denied (WITH CHECK); staff retains full external-client
  access; Partner sees everything; **074 rollback restores visibility** (proving
  074 is the enforcer). PASS.
- **Application layer (`test_batch2_internal_client.py`, 6 tests):** G1 view guard
  (404 for staff, ok for partner/owner), G1 id guard, G2 repo exclusion +
  `include_internal` opt-in + count, G4 payroll block. PASS.
- **Batch 1 harness:** still PASS (forward x2 idempotent + rollback).
- **Full regression:** **978 passed**; the **23 failures are the identical
  pre-existing Supabase-503 environmental DB tests** (phase3 gst/mca/tds +
  hardening) — unchanged before/after Batch 2 → **no regression**.

## 5. Migration risks

| Risk | Severity | Mitigation |
|---|---|---|
| Restrictive policy hides ordinary rows when `internal_client_id` is NULL | Med→Low | Used `IS DISTINCT FROM` so NULL never matches a real `client_id`; verified via harness with an unprovisioned-style path. |
| Over-broad exclusion regressing existing counts | Low | Existing rows are `is_internal=false`; behaviour identical until an internal client exists. Full suite unchanged (978). |
| Provisioning fails and blocks firm creation | Low | Hook is **non-fatal** (logs + continues); re-runnable via `POST /api/practice/provision`. |
| Service-role bypass means RLS alone is insufficient | Addressed | Dual-layer enforcement (API + RLS); API is the effective layer. |

## 6. Blockers / inputs for Batch 3 (Revenue Operations billing)

1. **G3 write-path:** Batch 3 creates the `client_firm_customer_links` row when a
   practice client is first billed (one customer in the internal client's books).
   The UNIQUE constraint already guarantees single-link.
2. **Entity type for provisioning** defaults to `Partnership`; the Practice UI
   (Batch 7) can let a Partner set the real firm entity type; `firms.pan` must be
   present/valid for provisioning to succeed (logged + skipped otherwise).
3. **fee_* bridge** (per `REVENUE_OPS_BRIDGE.md`): Batch 3 routes new billing
   through internal-client `sales_invoices`; existing `fee_*` stays read-only.

**Status: Batch 2 complete and passing. Awaiting review before Batch 3.**
