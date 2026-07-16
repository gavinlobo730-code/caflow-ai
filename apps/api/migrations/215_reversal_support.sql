-- Migration 215: Reverse-receipt / reverse-payment support (task #102).
--
-- cancel_invoice/cancel_purchase_bill refuse to cancel a document once it has
-- receipts/payments applied ("Reverse the receipt(s)/payment(s) first"), but
-- no endpoint existed to do that reversal safely. Neither receipts nor
-- purchase_payments carried any reversed/void marker, so there was no way to
-- record that a receipt/payment had been undone (and its GL journal reversed)
-- without deleting the row and losing the audit trail.

ALTER TABLE receipts ADD COLUMN IF NOT EXISTS is_reversed boolean NOT NULL DEFAULT false;
ALTER TABLE purchase_payments ADD COLUMN IF NOT EXISTS is_reversed boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN receipts.is_reversed IS
    'Set true by services/reversal_service.reverse_receipt() — the receipt no longer represents real money movement (its journal was reversed and its invoice allocations undone) but the row is kept for audit history.';
COMMENT ON COLUMN purchase_payments.is_reversed IS
    'Set true by services/reversal_service.reverse_payment() — the payment no longer represents real money movement (its journal was reversed and its bill claim undone) but the row is kept for audit history.';

-- receipt_allocations has no delete-on-reverse story (rows are FK'd from both
-- receipts and client_sales_invoices; deleting would erase which invoices a
-- reversed receipt used to fund, before the reversal, from the audit trail).
-- Voided instead, matching the reversed-not-deleted convention used
-- everywhere else in the accounting engine.
ALTER TABLE receipt_allocations ADD COLUMN IF NOT EXISTS is_voided boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN receipt_allocations.is_voided IS
    'Set true when the parent receipt is reversed. Excluded from customer_statement_service''s AR-relief calculation so a reversed receipt''s allocations no longer count toward what was collected.';
