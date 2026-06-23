-- Migration 123: Add 'Issued' to fee_invoices.status CHECK constraint
--
-- Problem: DB CHECK at migration 014 allows ('Draft','Sent','Paid','Overdue').
-- The application (invoices.py) writes 'Issued' (not 'Sent'), so every invoice
-- status transition to 'Issued' fails at the DB level with a CHECK violation.
-- The revenue filters also default to ['Issued','Paid'], meaning all billing
-- aggregates return zero for correctly-issued invoices.
--
-- Fix: widen the CHECK to allow both 'Issued' (app vocabulary) and 'Sent'
-- (original DB vocabulary, retained for any existing rows). 'Cancelled' added
-- for completeness (future soft-cancel flow).
-- Idempotent.

ALTER TABLE public.fee_invoices
  DROP CONSTRAINT IF EXISTS fee_invoices_status_check;

ALTER TABLE public.fee_invoices
  ADD CONSTRAINT fee_invoices_status_check CHECK (status IN (
    'Draft',
    'Issued',
    'Sent',
    'Paid',
    'Overdue',
    'Cancelled'
  ));

COMMENT ON CONSTRAINT fee_invoices_status_check ON public.fee_invoices IS
  'Allows both Issued (app vocabulary since Sprint 1) and Sent (original DB value). '
  'Widened in migration 123.';
