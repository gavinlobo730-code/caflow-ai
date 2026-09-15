-- Rollback for 385.
DROP TABLE IF EXISTS public.capital_gain_reinvestments;

ALTER TABLE public.capital_gains
  DROP CONSTRAINT IF EXISTS capital_gains_transferred_asset_nature_check;
ALTER TABLE public.capital_gains
  DROP COLUMN IF EXISTS transferred_asset_nature;
