-- Rollback for 372.
--
-- Dropping this column loses which of CGST Rule 43(1)'s three uses each asset
-- is put to -- a CA determination that no ledger, document or amount records,
-- so it cannot be rebuilt from anything else in the database. Export
-- fixed_assets(id, rule_43_use) WHERE rule_43_use IS NOT NULL before running
-- this.

DROP INDEX IF EXISTS public.idx_fixed_assets_rule_43_common;

ALTER TABLE public.fixed_assets
  DROP CONSTRAINT IF EXISTS fixed_assets_rule_43_use_check;

ALTER TABLE public.fixed_assets
  DROP COLUMN IF EXISTS rule_43_use;
