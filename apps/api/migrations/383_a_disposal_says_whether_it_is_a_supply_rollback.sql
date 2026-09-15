-- Rollback for 383.
DROP INDEX IF EXISTS public.idx_fixed_assets_disposal_gst;

ALTER TABLE public.fixed_assets
  DROP CONSTRAINT IF EXISTS fixed_assets_disposal_gst_rate_bps_check;

ALTER TABLE public.fixed_assets
  DROP COLUMN IF EXISTS disposal_is_interstate,
  DROP COLUMN IF EXISTS disposal_gst_rate_bps,
  DROP COLUMN IF EXISTS disposal_is_supply;
