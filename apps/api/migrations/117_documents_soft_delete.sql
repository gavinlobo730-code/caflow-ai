-- Migration 117: Documents soft-delete
-- Adds deleted_at and deleted_by columns to the documents table.
-- Soft deletion keeps audit trail — rows are hidden by application layer,
-- never permanently removed. Storage file cleanup is a separate async operation.

ALTER TABLE public.documents ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
ALTER TABLE public.documents ADD COLUMN IF NOT EXISTS deleted_by UUID;

COMMENT ON COLUMN public.documents.deleted_at IS
  'Soft-delete marker. NULL for live documents. Set when a CA deletes a document.';
COMMENT ON COLUMN public.documents.deleted_by IS
  'User who soft-deleted this document (references auth.users).';

CREATE INDEX IF NOT EXISTS idx_documents_not_deleted
  ON public.documents (firm_id, client_id, created_at DESC)
  WHERE deleted_at IS NULL;
