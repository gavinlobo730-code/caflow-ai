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

### Batch 2 (provisioning + guardrails) — *pending*
- To be recorded: how existing client-population queries are switched to
  `clients_external`; how `firms.pan`/entity-type feed provisioning.

### Batch 3+ (billing orchestration) — *pending*
- To be recorded: the adapter that lets existing fee/dues screens read from the
  new internal-client `sales_*` data, and any dual-write/compat shims.

## Rule

New Revenue Operations functionality MUST target the Amendment stack. The `fee_*`
tables are a **legacy compatibility layer only** — no new feature work extends
them. Retiring `fee_*` (data migration + endpoint deprecation) is out of scope
until explicitly approved.
