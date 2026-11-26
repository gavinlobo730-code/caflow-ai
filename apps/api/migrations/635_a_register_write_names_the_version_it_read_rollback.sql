-- Rollback of migration 635: drop the register version and its trigger. Safe to run twice; the API reads the column only where the row
-- carries it, so it runs without it.
DROP TRIGGER IF EXISTS trg_fixed_assets_bump_register_version ON public.fixed_assets;
DROP FUNCTION IF EXISTS public.fixed_assets_bump_register_version();
ALTER TABLE public.fixed_assets DROP COLUMN IF EXISTS register_version;
