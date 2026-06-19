-- PracticeSync AI — Migration 099: client_sales_invoices.issued_at
--
-- Adds an IMMUTABLE issuance timestamp, distinct from updated_at. updated_at
-- mutates on every edit (reminders, ageing recompute, payment updates), so it
-- cannot represent the legal moment of issuance. issued_at is set once, when the
-- invoice transitions draft → issued (i.e. when its posted journal is created),
-- and is required for GST compliance, reminder scheduling, ageing, delivery
-- tracking, and the audit trail.
--
-- CGST Act §31: a registered person supplying taxable goods/services shall issue
-- a tax invoice; the issuance date drives GSTR-1 period and downstream timelines.
--
-- Additive, idempotent, backward-compatible. No financial data is changed.

ALTER TABLE client_sales_invoices ADD COLUMN IF NOT EXISTS issued_at TIMESTAMPTZ;

COMMENT ON COLUMN client_sales_invoices.issued_at IS
  'Immutable timestamp when the invoice transitioned draft -> issued (its posted '
  'journal was created). Distinct from updated_at, which changes on every edit. '
  'NULL while the invoice is still a draft. CGST Act §31.';

-- Backfill existing issued invoices that predate this column. updated_at is the
-- best available proxy for the original issuance moment. Only fills NULLs so the
-- migration is safe to re-run and never overwrites a real issuance timestamp.
UPDATE client_sales_invoices
   SET issued_at = updated_at
 WHERE issued_at IS NULL
   AND status = 'issued';
