# Revenue Operations — Bridge & Technical-Debt Register

Per the approved billing decision (**Amendment model; bridge `fee_*`**), the
long-term billing substrate is the **firm-as-internal-client** reusing the
`sales_*` / `receipts` accounting stack. The legacy `fee_engagements` /
`fee_invoices` / `fee_receipts` stack remains **readable for historical data**;
**no historical fee data is migrated** until a future migration phase is
explicitly approved. This document records every bridge point and the technical
debt the compatibility layer carries. It is updated as each batch lands.

## Target vs legacy

| Concern | Target (Amendment) | Legacy (compat, read-only path) |
|---|---|---|
| Firm's invoices to clients | `sales_invoices` / `sales_invoice_lines` owned by the **internal client** | `fee_invoices` |
| Receipts / collections | `receipts` (client books) | `fee_receipts` |
| Billing arrangement / cadence | `billing_schedules` (new) | `fee_engagements.billing_cycle` |
| Practice client ↔ books customer | `client_firm_customer_links` → `customers` | (none; `fee_*` keyed by `client_id` directly) |
| Credit notes | existing `credit_notes` mechanism | n/a |

## Bridge points / technical debt (by batch)

### Batch 1 (schema foundation)
- **B1-1 · `time_entries.billable_rate_paise` coexists with legacy
  `hourly_rate_paise`.** New Amendment-conformant column added; the legacy
  `INTEGER` `hourly_rate_paise` is left untouched. Readers must prefer
  `billable_rate_paise` when present, else fall back to `hourly_rate_paise`.
  *Debt:* two rate columns until a future consolidation phase.
- **B1-2 · `billing_schedules.service_id` has no FK.** The Amendment references
  `service_catalogue`, which does not exist in this codebase. `service_id` is a
  nullable `uuid` with no foreign key. *Debt:* add the FK if/when a
  `service_catalogue` table is introduced.
- **B1-3 · `fee_*` remains the only live billing path until Batch 3.** Batch 1
  is schema-only; no code yet writes `billing_schedules` or internal-client
  `sales_invoices`. Existing `fee_*` endpoints/screens are unchanged.

### Batch 2 (provisioning + guardrails)
- **B2-1 · Service-role bypasses RLS.** The backend uses the Supabase
  SERVICE_ROLE key, so RLS is *not* the effective control for the app. G1/G2/G4
  are enforced in the Python repo/API layer; migration `074` RLS restrictive
  policies are defence-in-depth for direct/PostgREST access. *Debt:* two
  enforcement layers must be kept in sync if new client-scoped tables/endpoints
  are added.
- **B2-2 · G2 via repository default + targeted patches.** `client_repo.find_all`
  excludes internal by default; a few direct `db.table("clients")` queries
  (Health recalc, Analytics, Onboarding status) were patched individually.
  *Debt:* any *new* direct `clients` query must remember to exclude
  `is_internal` (or use `client_repo`/`clients_external`).
- **B2-3 · Provisioning inputs.** Internal-client `entity_type` defaults to
  `Partnership` (CA-firm typical) and PAN comes from `firms.pan`; provisioning is
  skipped (logged) when no valid PAN exists. Re-runnable via
  `POST /api/practice/provision`.
- **B2-4 · `provision()` duplicates the SQL `provision_internal_client()`.** The
  Python service is the runtime path (works with service-role + mock); the SQL
  function (migration 073) remains a DB-callable foundation. *Debt:* keep the two
  in step (both idempotent, same insert + link).

### Batch 3 (billing orchestration)
- **B3-1 · Real table is `client_sales_invoices`** (not Doc-5 `sales_invoices`).
  Billing reuses it; migration 075 added `billing_schedule_id`, `billing_period`,
  `source` + the unique idempotency index + the G1 restrictive policy (which 074
  had missed because it referenced the non-existent `sales_invoices`).
- **B3-2 · Billing reuses `create_invoice`** (the router function) rather than a
  service, to guarantee a single GST/insert path. *Debt:* if the Sales engine is
  later refactored into a service, billing should call that service instead.
- **B3-3 · `fee_*` dues vs new billing.** `GET /api/portal/dues` and the legacy
  invoice screens still read `fee_*`. New Revenue Operations dues live in
  `client_sales_invoices` (internal client). A read-adapter to unify the two
  surfaces is **deferred** (no dual-write; `fee_*` stays read-only legacy).
- **B3-4 · Internal-client CoA.** RESOLVED in Batch 3.1: firm-wide master CoA is
  seeded at onboarding (`services/coa_seed_service.seed_firm_coa`, client_id NULL,
  Migration-057 architecture) with names matching the posting patterns. The
  internal client posts via the shared firm CoA. Existing firms: re-run the seed
  (idempotent) as a deployment step.

### Batch 3.1 (accounting hardening)
- **B3.1-1 · Atomic issue.** `issue_invoice` posts the journal before flipping to
  `issued` (stores `journal_entry_id`, migration 076). Missing CoA → invoice stays
  a re-tryable draft. *Residual:* status update + journal insert are two statements
  (not one SQL txn); a crash between them leaves a posted journal with a draft
  invoice — re-issue is safe (`_create_journal` de-dups). Full txn wrapping deferred.
- **B3.1-2 · Recovery.** `GET /api/sales-invoices/maintenance/unposted` +
  `POST /api/sales-invoices/{id}/repost-journal` detect/remediate any legacy
  issued-but-unposted invoices (idempotent, Partner-only for the internal client).

### Batch 4 (collections & AR)
- **B4-1 · Overdue is derived, not a status.** `is_overdue`/`days_overdue`/
  `aging_bucket` (migration 077) are maintained by a daily sweep; payment status
  is never mutated to `overdue`. Legacy `fee_*` overdue (status-based, via
  `invoice_lifecycle_service`) is untouched — the two models coexist on different
  tables.
- **B4-2 · TDS on fees via the receipts engine.** `receipts.tds_paise` extends the
  existing receipt; `journal_for_receipt` posts the `Dr TDS Receivable` leg.
  Single receipts/accounting path (no separate TDS workflow).
- **B4-3 · Aging fallback.** When `due_date` is absent, aging derives
  `invoice_date + 30` (default credit days). Refining with `customers.credit_days`
  per invoice is a minor future enhancement.
- **B4-4 · Dashboard scope.** Firm Collections/AR KPIs aggregate the internal
  client's fee invoices (Partner-only). DSO/realization remain deferred Revenue
  Intelligence.

### Batch 5 (billable / cost-rate capture)
- **B5-1 · System-controlled billed linkage.** `time_entries.billed_invoice_id`
  is authoritative; `is_billed` is a GENERATED column (manual write rejected).
  Future time-based billing sets `billed_invoice_id` via
  `billing_service.mark_time_entries_billed`; no endpoint edits `is_billed`.
- **B5-2 · Capture only.** `cost_rate_paise` is partner-visible capture/display
  only — never used in computation. Realization/margin/profitability/forecasting/
  utilization remain deferred (Revenue Intelligence, Phase 13+).
- **B5-3 · Time repo is DB-only.** No mock path; unbilled-work logic lives in pure
  helpers (`unbilled_value_paise`, `group_unbilled`) so it is unit-testable, with
  the migration verified via the SQL harness.

## Rule

New Revenue Operations functionality MUST target the Amendment stack. The `fee_*`
tables are a **legacy compatibility layer only** — no new feature work extends
them. Retiring `fee_*` (data migration + endpoint deprecation) is out of scope
until explicitly approved.
