-- Migration 247: invoice-level round-off becomes opt-in (Product Owner-approved
-- product direction change).
--
-- Adds client_sales_invoices.round_off_enabled (default FALSE — every invoice
-- now preserves its exact calculated amount unless the CA explicitly turns
-- rounding on for that invoice). This does not remove round_off_paise, the
-- 'Round Off' ledger, or journal_for_sales_invoice's round-off posting logic —
-- those are all reused unchanged; this column only gates whether they fire.
--
-- Schema-only. The one-time correction of EXISTING invoices/journals that
-- previously had mandatory round-off applied is a separate data migration
-- (248_remove_mandatory_invoice_round_off.sql), since it posts real journal
-- entries and isn't pure DDL.

ALTER TABLE public.client_sales_invoices
  ADD COLUMN IF NOT EXISTS round_off_enabled BOOLEAN NOT NULL DEFAULT FALSE;
