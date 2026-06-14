# Batch 3 Completion Report — Revenue Operations (recurring billing via Sales reuse)

**Amendment v1.1 (Phase 10B) · Batch 3 of 7 · Branch:** `claude/compassionate-darwin-nffpnb`
**Date:** 2026-06-14 · **Migration:** `075_billing_traceability.sql` (+ rollback)

## Scope adherence

- **Bridge preserved:** `fee_*` untouched (readable, no migration, no retirement). All
  new Revenue Operations route through the existing **`client_sales_invoices`** Sales
  engine in the internal client's books. (Note: the real table is
  `client_sales_invoices`, not the Doc-5 name `sales_invoices`.)
- **No second GST/accounting impl:** billing calls the existing
  `routers.sales_invoices.create_invoice` (GST via `_compute_line_gst`, numbering,
  insert, timeline) and posts journals via the existing `issue` path
  (`phase2_journal_service`). The billing service owns no ledger/GST logic.

## 1. Invoice lifecycle

```
 billing_schedule (due)
        │  billing.generate  (idempotent, DRAFT only)
        ▼
   ┌─────────┐  CA-confirm gate           ┌──────────┐  receipt (full)   ┌────────┐
   │  DRAFT  │ ─────────────────────────► │  ISSUED  │ ────────────────► │  PAID  │
   │ (raised)│  POST /sales-invoices/      │ (sent)   │                   └────────┘
   └─────────┘   {id}/issue  → posts JE    └──────────┘  receipt (part)        ▲
        │         (Partner-gated, G1)           │ ───────────────► PARTIALLY_PAID
        │                                       │                         │
        └── cancel (Partner) ──► CANCELLED      └──────── (Batch 4: aging → OVERDUE)
```

- **Generation** produces a **DRAFT** only — never auto-issued, never auto-sent.
- **CA-confirm gate** = the existing draft→issue transition, which posts the
  double-entry journal and is **Partner-gated** for the internal client (Batch 2.1).
- **Collections** reuse the existing receipts engine (`POST /api/receipts`), which
  updates `paid_paise` + status (`partially_paid`/`paid`) and posts the receipt
  journal. AR aging + `OVERDUE` + reminders are Batch 4.

## 2. Billing data flow

```
billing_schedules ──(client_id = practice client)──► ensure_customer_link (G3)
        │                                                      │
        │ amount_paise, gst_rate, cadence                      ▼
        │                                          customers (in internal client's books)
        ▼                                                      │ internal_customer_id
 billing_service.generate_for_schedule                         │
        │  builds SalesInvoiceIn(client_id=internal, customer_id=link, line@SAC 998211)
        ▼
 routers.sales_invoices.create_invoice  ── REUSE: GST (_compute_line_gst) + insert
        │                                   into client_sales_invoices (DRAFT)
        ▼
 _stamp_billing_fields  ── billing_schedule_id + billing_period + source='billing'
        │                  (UNIQUE index = duplicate backstop)
        ▼
 _advance_schedule (next_run_date by cadence; one_time → is_active=false)
```

**Traceability of every generated invoice:**
`client_sales_invoices.billing_schedule_id → billing_schedules.id` (and
`billing_schedules.client_id` = the **originating practice client**);
`client_sales_invoices.customer_id` = the **linked customer**
(`client_firm_customer_links.internal_customer_id`); `billing_period` = the covered period.

## 3. Idempotency strategy

1. **Deterministic period key** per cadence (`period_for`): `monthly→YYYY-MM`,
   `quarterly→YYYY-Qn`, `annual→Indian FY`, `one_time→ONCE`.
2. **Existence check (fast path):** before generating, look up an invoice with the
   same `(billing_schedule_id, billing_period)`; if found, return it with
   `created=False, idempotent=True` — **replay-safe**.
3. **Schedule advance:** after a successful generate, `next_run_date` advances by
   cadence (one_time closes the schedule), so a re-run is not "due".
4. **Accounting replay-safety:** the existing `_create_journal` skips duplicate
   journals (same `reference_no + entry_date + client_id`), so re-issuing cannot
   double-post.

## 4. Duplicate-prevention strategy

1. **Authoritative DB guard:** `UNIQUE INDEX uq_client_sales_invoices_billing_run
   (billing_schedule_id, billing_period) WHERE billing_schedule_id IS NOT NULL`
   (migration 075) — at most one invoice per schedule/period even under concurrent
   runs.
2. **Race handling:** if two runs both pass the existence check and create drafts,
   the second `_stamp_billing_fields` hits the unique violation → the orphan **draft**
   (no journal posted) is deleted and the winning invoice is returned.
3. **G3 single customer link:** `client_firm_customer_links UNIQUE(firm_id, client_id)`
   guarantees one customer per practice client; `ensure_customer_link` handles the
   race (deletes the spare customer, returns the winner).

## 5. Files

**New:** `services/billing_service.py` (orchestration), `routers/billing.py`
(Partner-only endpoints), `migrations/075_billing_traceability.sql` (+ rollback),
`tests/test_batch3_billing.py`, `tests/test_batch3_billing_migration.py`,
`tests/sql/batch3_billing_verify.sql`.
**Modified:** `core/permissions.py` (Partner-only `billing` resource), `main.py`
(register billing router).

**Endpoints (Partner-only):** `GET/POST /api/billing/schedules`,
`POST /api/billing/preview-run`, `POST /api/billing/schedules/{id}/generate`,
`POST /api/billing/run`. CA-confirm reuses `POST /api/sales-invoices/{id}/issue`;
collections reuse `POST /api/receipts`; credit notes reuse `/api/credit-notes`.

## 6. Test results

**Application layer — `test_batch3_billing.py` (8, mock):** recurring generation;
**GST correctness** (₹1,000 @18% → CGST 9,000 + SGST 9,000 = total 1,18,000 paise,
via the reused engine); traceability fields; **duplicate-run protection**
(idempotent, one invoice); **customer-link single** per practice client (G3);
**CA-confirm gate** (draft until issued); preview-run; **partner-only** RBAC;
period/cadence helpers. PASS.

**DB guarantees — `test_batch3_billing_migration.py` + SQL harness (real PG):**
duplicate `(schedule, period)` insert rejected by the unique index; different
period allowed; **G3** duplicate link rejected; **restrictive G1 RLS** on
`client_sales_invoices` (staff see 0 internal invoices, partner sees all);
**collections lifecycle** raised→partially_paid→paid with traceability preserved;
clean **075 rollback**. PASS.

**Regression:** full suite **992 passed**; the **same 23 pre-existing Supabase-503
environmental failures** — no regression.

## 7. Notes / blockers for Batch 4

1. **Internal-client Chart of Accounts:** issuing (posting the JE) resolves GL
   accounts via `_find_account` (firm-wide `client_id IS NULL` **or** client-specific).
   For production the internal client needs Trade Receivables / Sales / GST Output /
   Bank accounts available (firm-wide or seeded). Reuse the existing per-client CoA
   seeding during provisioning — tracked for Batch 4/deployment (does not affect
   draft generation or mock tests).
2. **Batch 4 builds on this:** AR aging buckets (0–30/31–60/61–90/>90), `OVERDUE`
   transition, automated reminders, GST/TDS-on-fees receivable, firm Collections/AR
   dashboard — all over the invoices/receipts produced here.

**Status: Batch 3 complete and passing. Awaiting review before Batch 4.**
