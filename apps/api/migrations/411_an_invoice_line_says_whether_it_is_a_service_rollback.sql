-- Rollback for 411. Dropping the column loses whatever CAs have recorded since
-- it landed, which is a fact about their documents rather than a derivation —
-- so this is the undo for a migration that has just been applied and found
-- wrong, not a routine step.

ALTER TABLE public.client_sales_invoice_lines
  DROP COLUMN IF EXISTS is_service;
