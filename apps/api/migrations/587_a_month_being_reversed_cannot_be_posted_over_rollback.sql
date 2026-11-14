-- Rollback of migration 587: drop the reversal marker. The marker is only ever set while a reversal is in flight, so dropping it loses
-- nothing that is not rewritten by the next reversal; run it with no reversal in flight. Safe to run twice.

ALTER TABLE public.fixed_assets DROP CONSTRAINT IF EXISTS fixed_assets_reversal_marker_is_a_month;
ALTER TABLE public.fixed_assets DROP CONSTRAINT IF EXISTS fixed_assets_reversal_marker_is_whole;
ALTER TABLE public.fixed_assets DROP COLUMN IF EXISTS depreciation_reversal_claimed_at;
ALTER TABLE public.fixed_assets DROP COLUMN IF EXISTS depreciation_reversal_month;
