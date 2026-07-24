-- Migration 236: track the foreign-currency amount on each allocation row,
-- so a reversal can roll back paid_txn correctly.
--
-- Task #227 audit finding: create_foreign_receipt / create_foreign_payment_core
-- track each invoice/bill's cumulative SETTLED FOREIGN amount on paid_txn
-- (separately from paid_paise, the base-currency AR/AP relief) so partial FX
-- settlements never drift. But receipt_allocations / purchase_payment_allocations
-- only ever recorded the base-currency allocated_paise — the foreign amount
-- actually allocated was discarded. reversal_service's _rollback_invoice_paid /
-- _rollback_bill_paid therefore could only roll back paid_paise; paid_txn stayed
-- permanently inflated after reversing any receipt/payment that touched a
-- foreign-currency document — understating that document's true outstanding in
-- its billing currency (foreign_out = txn_total - paid_txn) forever after.
--
-- allocated_txn is nullable and defaults to nothing for existing/domestic rows
-- (paid_txn is always 0 for a plain-INR document, so there is nothing to roll
-- back) — reversal_service treats a NULL/absent value as 0.
ALTER TABLE receipt_allocations
  ADD COLUMN IF NOT EXISTS allocated_txn BIGINT;

ALTER TABLE public.purchase_payment_allocations
  ADD COLUMN IF NOT EXISTS allocated_txn BIGINT;
