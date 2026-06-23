-- Migration 118: fee_invoices soft-delete
-- Financial records must never be hard-deleted. Adds is_deleted, deleted_at,
-- deleted_by to fee_invoices for application-layer soft-deletion.
-- Only Draft invoices may be deleted (enforced in application layer).

ALTER TABLE public.fee_invoices ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE public.fee_invoices ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
ALTER TABLE public.fee_invoices ADD COLUMN IF NOT EXISTS deleted_by UUID;

COMMENT ON COLUMN public.fee_invoices.is_deleted IS
  'Soft-delete flag. Only Draft invoices may be soft-deleted.';
COMMENT ON COLUMN public.fee_invoices.deleted_at IS
  'Timestamp when this Draft invoice was discarded.';

-- Partial index for active (non-deleted) invoice listing
CREATE INDEX IF NOT EXISTS idx_fee_invoices_not_deleted
  ON public.fee_invoices (firm_id, client_id, created_at DESC)
  WHERE is_deleted = false;
