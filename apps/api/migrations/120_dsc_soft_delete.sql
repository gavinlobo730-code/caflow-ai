-- Migration 120: DSC records soft-delete + audit support
-- The dsc_records table (migration 014) already has the correct columns
-- (issued_date, issued_by, token_no). This adds soft-deletion so DSC history
-- is preserved and never hard-deleted, consistent with the platform model.

ALTER TABLE public.dsc_records ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
ALTER TABLE public.dsc_records ADD COLUMN IF NOT EXISTS deleted_by UUID;

COMMENT ON COLUMN public.dsc_records.deleted_at IS
  'Soft-delete marker. NULL for live DSC records.';
COMMENT ON COLUMN public.dsc_records.deleted_by IS
  'User who soft-deleted this DSC record (references auth.users).';

CREATE INDEX IF NOT EXISTS idx_dsc_records_firm_live
  ON public.dsc_records (firm_id, expiry_date)
  WHERE deleted_at IS NULL;

-- ── updated_at trigger ───────────────────────────────────────────────────────
-- Migration 014 created dsc_records without a BEFORE UPDATE trigger (updated_at
-- only got its INSERT default of NOW()). Add one so updated_at is maintained on
-- every UPDATE, reusing the shared set_updated_at() function (migration 001).
-- Guarded so re-running this migration is safe.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'trg_dsc_records_updated_at'
  ) THEN
    CREATE TRIGGER trg_dsc_records_updated_at
      BEFORE UPDATE ON public.dsc_records
      FOR EACH ROW EXECUTE FUNCTION set_updated_at();
  END IF;
END$$;
