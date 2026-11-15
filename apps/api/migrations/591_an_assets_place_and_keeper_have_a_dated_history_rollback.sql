-- Rollback of migration 591: the movement history, its function and the keeper column go. The register keeps each asset's current
-- location (it was always on the asset); the keeper recorded since 591 is lost with the column.
BEGIN;
DROP FUNCTION IF EXISTS public.record_fixed_asset_movement(uuid, uuid, uuid, date, text, text, text, text, text, uuid);
DROP TABLE IF EXISTS public.fixed_asset_movements;
ALTER TABLE public.fixed_assets DROP CONSTRAINT IF EXISTS fixed_assets_custodian_is_a_line;
ALTER TABLE public.fixed_assets DROP COLUMN IF EXISTS custodian;
COMMIT;
