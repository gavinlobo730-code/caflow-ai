-- Rollback for 406.
--
-- ⚠️ BOTH COLUMNS HOLD A CA'S OWN JUDGEMENT AND NOTHING CAN RE-DERIVE THEM.
-- Whether an assessee is engaged in manufacture or production, and whether a
-- particular machine is new plant the first proviso does not exclude, are
-- facts no ledger holds — that is the whole reason they are columns. Export
-- both before running this:
--
--   SELECT id, section_32_1_iia_business FROM public.clients
--    WHERE section_32_1_iia_business IS NOT NULL;
--   SELECT id, additional_depreciation_eligible FROM public.fixed_assets
--    WHERE additional_depreciation_eligible IS NOT NULL;

DROP INDEX IF EXISTS public.idx_fixed_assets_additional_depreciation;

ALTER TABLE public.fixed_assets
  DROP COLUMN IF EXISTS additional_depreciation_eligible;

ALTER TABLE public.clients
  DROP COLUMN IF EXISTS section_32_1_iia_business;
