# Batch 5 Completion Report — Billable flags, staff cost rates, unbilled-work visibility

**Amendment v1.1 (Phase 10B) · Batch 5 of 7 · Branch:** `claude/compassionate-darwin-nffpnb`
**Date:** 2026-06-14 · **Migration:** `078_billable_capture.sql` (+ rollback)

**Strictly a data-capture + visibility layer.** No realization, margin, profitability,
forecasting, utilization analytics, or Revenue Intelligence (all remain deferred,
FR-RI Phase 13+). `cost_rate_paise` is captured + partner-visible but is **never
used in any computation** in this batch.

## 1. What was implemented (allowed scope only)
- **Billable flag + billable rate capture:** `time_entries.is_billable` and
  `billable_rate_paise` (Batch-1 columns) are now captured via the time-entry
  create/update API (`ManualEntryCreate`, `EntryUpdate`).
- **Staff cost-rate capture:** `users.cost_rate_paise` via Partner-only
  `GET/PUT /api/billing/staff-cost-rates`.
- **Unbilled-work visibility:** Partner-only `GET /api/billing/unbilled-work` —
  billable, not-yet-billed time grouped by client/work item with **billable value
  = minutes × rate ÷ 60** (integer paise; `billable_rate_paise` else
  `hourly_rate_paise`).

## 2. System-controlled billed linkage (per requirement)
- `time_entries.billed_invoice_id` is the **authoritative** linkage (FK →
  `client_sales_invoices`, `ON DELETE SET NULL`).
- `time_entries.is_billed` is a **`GENERATED ALWAYS AS (billed_invoice_id IS NOT
  NULL) STORED`** column — so it always reflects the linkage (no reconciliation)
  and **cannot be set manually** (Postgres rejects writes to generated columns).
- `is_billed`/`billed_invoice_id` are **absent from every input model** — not
  editable via the API. A system function `billing_service.mark_time_entries_billed`
  sets `billed_invoice_id` for future time-based billing; future workflows can rely
  on these fields without reconciliation.

## 3. Guardrails / scope control
- Cost rates + unbilled view are **Partner-only** (fee economics, G1).
- `cost_rate_paise` is capture/display only — verified **not** used in unbilled
  value or anywhere else.
- No analytics tables, no new computed metrics beyond billable value of unbilled work.

## 4. Files
**New:** `migrations/078_billable_capture.sql` (+ rollback),
`tests/test_batch5_capture.py`, `tests/test_batch5_migration.py`,
`tests/sql/batch5_capture_verify.sql`.
**Modified:** `routers/time_tracking.py` (capture `billable_rate_paise`; `is_billed`
deliberately not exposed), `services/billing_service.py` (unbilled helpers,
cost-rate capture, `mark_time_entries_billed`), `routers/billing.py` (Partner-only
endpoints).

## 5. Test results
- **Application (`test_batch5_capture.py`, 8, mock):** unbilled value arithmetic
  (integer paise, billable-rate-preferred, hourly fallback); `group_unbilled`
  filtering (excludes billed / non-billable / zero-minute) + grouping by
  client/work-item; cost-rate capture + non-negative validation; **cost rate not
  used in unbilled value**; **`is_billed`/`billed_invoice_id` absent from input
  models** (cannot be edited); partner-only RBAC. PASS.
- **DB guarantees (`test_batch5_migration.py` + SQL harness, real PG):** capture
  columns present; `is_billed` is GENERATED; **derives from `billed_invoice_id`**;
  **manual write to `is_billed` rejected** (`generated_always`); unbilled query;
  clean 078 rollback. PASS.
- **Regression:** full suite **1016 passed**; the same **23 pre-existing
  Supabase-503 environmental failures** — no regression.

## 6. Residual notes
- Time-entry repository is DB-only (no mock path), so unbilled-work integration is
  exercised via the SQL harness + pure-helper unit tests; the API path is thin.
- `mark_time_entries_billed` exists for future time-based billing; no current
  workflow calls it (fixed-fee billing in Batch 3 doesn't consume time entries).
- **Deferred (unchanged):** realization, margin, profitability, forecasting,
  utilization analytics, Revenue Intelligence.

**Status: Batch 5 complete and passing. Holding before Batch 6 (Knowledge Base + client instructions).**
