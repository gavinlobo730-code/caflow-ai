# Batch 4 Completion Report — Collections, AR Aging, GST/TDS on fees, Dashboard

**Amendment v1.1 (Phase 10B) · Batch 4 of 7 · Branch:** `claude/compassionate-darwin-nffpnb`
**Date:** 2026-06-14 · **Migration:** `077_collections_ar.sql` (+ rollback)

Built on the validated design. Operates on the **internal client's** fee invoices
(firm AR), Partner-only (G1), reusing the Sales/receipts engines — no second
accounting/GST implementation.

## 1. AR aging (due-date based)
- `days_overdue = today − reference_date`; `reference_date = invoice.due_date`
  else `invoice_date + credit_days` (default 30). Same calculation everywhere
  (aging, overdue, reminders, KPIs) for consistent reporting.
- Buckets: **not_due**, **0-30**, **31-60**, **61-90**, **90+**, over open invoices
  (`issued`/`partially_paid`, outstanding > 0). Per-bucket paise + counts.

## 2. Overdue transition — derived + denormalised (no status mutation)
- Payment statuses preserved (`draft/issued/partially_paid/paid/cancelled`); **no
  `overdue` status**. Collections metadata `is_overdue` / `days_overdue` /
  `aging_bucket` (migration 077) is maintained by an idempotent daily **sweep**.
  `is_overdue = (due_date < today AND outstanding > 0)`; paid invoices are never
  overdue. Result e.g. "Partially Paid + 45 days overdue".

## 3. Reminder scheduling
- `send_overdue_reminders`: for overdue invoices not reminded within
  `REMINDER_INTERVAL_DAYS` (7) — sets `last_reminded_at`/`reminder_count`, writes a
  Timeline event (anti-spam, idempotent). Wired into the per-firm daily
  `jobs/scheduler.py` (job #4, `collections`) alongside the sweep. In-app/Timeline
  now; portal/WhatsApp mirroring deferred to Batch 7+.

## 4. GST on fees — clarified (no GST receivable)
- GST on professional fees is **OUTPUT tax (a liability)**, posted at issue in
  Batch 3 (`Cr GST Output Tax Payable`). The client owes fee **+ GST**, so GST is
  part of **Trade Receivables** (AR `outstanding` includes it). There is **no
  GST-receivable** artifact for the firm's own sales (ITC is a purchase concept).

## 5. TDS on fees — receivable via the receipts engine
- Clients deduct **194J TDS (10%)**; captured as optional `receipts.tds_paise`.
  Settlement = `amount_paise + tds_paise`. The receipt journal now posts
  `Dr Bank (cash) + Dr TDS Receivable (tds) + Cr Trade Receivables (cash+tds)`
  (extended `journal_for_receipt`), so an invoice can be **PAID even when cash <
  invoice value**. Once settled, outstanding = 0 → it leaves AR; TDS is reported
  separately and reconciles to 26AS/AIS via the existing flow.

## 6. Dashboard KPIs (Partner-only, operational)
`GET /api/billing/collections/dashboard`: **total receivable**, **aging** (5
buckets), **overdue paise + count**, **TDS receivable** (Σ `receipts.tds_paise`),
**collected cash** (Σ `receipts.amount_paise` in window). Plus `GET /api/billing/ar-aging`,
`POST /api/billing/collections/sweep`, `POST /api/billing/collections/send-reminders`.
**Deferred (Revenue Intelligence, FR-RI, Phase 13+):** DSO, realization, recovery
rate, forecasting — Batch 4 is operational only.

## 7. Reuse points
`client_sales_invoices` (status/paid/total/due_date) → AR source; **receipts
engine** (now `tds_paise`-aware) → collections; `phase2_journal_service.journal_for_receipt`
(extended, single accounting path); `billing_service` + `client_firm_customer_links`
→ internal-client scope; `jobs/scheduler.py` → daily sweep + reminders;
`timeline_service`; `internal_client_service` (Partner-only, G1); seeded **TDS
Receivable** CoA (Batch 3.1); existing 26AS/AIS reconciliation.

## 8. Files
**New:** `services/collections_service.py`, `migrations/077_collections_ar.sql`
(+ rollback), `tests/test_batch4_collections.py`, `tests/test_batch4_migration.py`,
`tests/sql/batch4_collections_verify.sql`.
**Modified:** `services/phase2_journal_service.py` (TDS leg on receipt journal),
`models/invoices.py` (`ReceiptIn.tds_paise` + settlement validation),
`routers/receipts.py` (TDS settlement), `routers/billing.py` (AR/collections
endpoints), `jobs/scheduler.py` (collections job).

## 9. Test results
- **Application (`test_batch4_collections.py`, 8, mock):** aging buckets (due-date),
  derived overdue flags with payment status preserved, dashboard KPIs incl. TDS +
  cash, reminder idempotency, ReceiptIn TDS settlement validation, bucket
  boundaries, due-date fallback, partner-only. PASS.
- **DB guarantees (`test_batch4_migration.py` + SQL harness, real PG):** migration
  077 columns; due-date aging at the data layer (not_due/0-30/61-90/90+, paid
  excluded); **balanced TDS receipt settlement** (108000 cash + 10000 TDS = 118000;
  invoice PAID with cash < invoice value; journal balances); clean 077 rollback. PASS.
- **Regression:** full suite **1008 passed**; the same **23 pre-existing
  Supabase-503 environmental failures** — no regression.

## 10. Residual notes
- **Reminder channels:** in-app/Timeline only; portal/WhatsApp mirroring is Batch 7+.
- **Per-customer credit_days:** aging fallback uses a 30-day default; refining the
  fallback with `customers.credit_days` (per invoice) is a minor enhancement
  (invoices with an explicit `due_date` are unaffected).
- **DSO/realization** intentionally excluded (Revenue Intelligence, deferred).

**Status: Batch 4 complete and passing. Awaiting review before Batch 5.**
