-- 161 — Widen receipts/purchase_payments.payment_mode CHECK constraints
-- (R2.12 adversarial-review finding, CONFIRMED critical).
--
-- Problem
-- -------
-- receipts.payment_mode and purchase_payments.payment_mode (migration 050)
-- both CHECK (payment_mode IN ('bank','cash','cheque','upi','neft','rtgs')).
-- Two real callers have never actually satisfied this constraint against a
-- real (non-mock) Postgres database:
--   * services/payment_service.py::_settle (the online-payment gateway
--     webhook settlement path) hardcodes payment_mode="online" for every
--     receipt it creates — not in the allowed set.
--   * models/invoices.py's ReceiptIn/PurchasePaymentIn both default
--     payment_mode to "bank_transfer" — also not in the allowed set, so any
--     caller (API or test) that omits payment_mode hits the same violation.
-- Discovered via R2.12's real-Postgres proof of settle_receipt_atomic
-- (migration 160): calling it with the payload services/payment_service.py
-- actually builds fails with "violates check constraint
-- receipts_payment_mode_check" — meaning the online-payments feature could
-- never successfully record a single receipt against a real database. This
-- predates migration 160 (the CHECK dates to migration 050; the Pydantic
-- defaults predate this session) but was only surfaced by this milestone's
-- real-Postgres testing, since mock mode never enforces the constraint.
--
-- Fix
-- ---
-- "online" is a real, distinct payment channel (a payment-gateway capture,
-- as opposed to a manually-entered bank/cash/cheque/UPI/NEFT/RTGS receipt) —
-- widen both CHECK constraints to accept it. "bank_transfer" is NOT added:
-- it was never a real distinct value, just a Pydantic default that should
-- have read "bank" all along (fixed in models/invoices.py in the same
-- commit as this migration) — every other caller in the codebase already
-- passes one of the six original values, so accepting "bank_transfer" too
-- would just perpetuate a naming inconsistency rather than fix it.
DO $$
BEGIN
  ALTER TABLE public.receipts DROP CONSTRAINT IF EXISTS receipts_payment_mode_check;
  ALTER TABLE public.receipts
    ADD CONSTRAINT receipts_payment_mode_check
    CHECK (payment_mode IN ('bank','cash','cheque','upi','neft','rtgs','online'));
END $$;

DO $$
BEGIN
  ALTER TABLE public.purchase_payments DROP CONSTRAINT IF EXISTS purchase_payments_payment_mode_check;
  ALTER TABLE public.purchase_payments
    ADD CONSTRAINT purchase_payments_payment_mode_check
    CHECK (payment_mode IN ('bank','cash','cheque','upi','neft','rtgs','online'));
END $$;
