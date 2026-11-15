-- Rollback of migration 592: the physical verification tables and their functions go; nothing else was changed by 592.
BEGIN;
DROP FUNCTION IF EXISTS public.close_fixed_asset_verification(uuid, uuid, uuid, uuid);
DROP FUNCTION IF EXISTS public.record_fixed_asset_finding(uuid, uuid, uuid, uuid, text, text, text, uuid);
DROP FUNCTION IF EXISTS public.fixed_asset_held_on(public.fixed_assets, date);
DROP TABLE IF EXISTS public.fixed_asset_verification_findings;
DROP TABLE IF EXISTS public.fixed_asset_verifications;
COMMIT;
