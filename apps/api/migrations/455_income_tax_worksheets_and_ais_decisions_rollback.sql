-- Rollback for 455.
--
-- Dropping these tables LOSES the CA's house-property and salary working
-- papers and every accept or reject recorded against an AIS line. Neither is
-- recoverable from anywhere else: the worksheets hold INPUTS that exist only
-- here (the derived figures are recomputed from them), and a decision is a
-- person's judgement about a statement. Export both first:
--   SELECT * FROM public.income_tax_worksheets;
--   SELECT * FROM public.ais_computation_decisions;
--
-- The computation screens then show no worksheet and no suggestion and fall
-- back to the single typed boxes they had before. No ledger, return or filing
-- reads either table, so nothing else moves.

DROP TABLE IF EXISTS public.ais_computation_decisions;
DROP TABLE IF EXISTS public.income_tax_worksheets;
