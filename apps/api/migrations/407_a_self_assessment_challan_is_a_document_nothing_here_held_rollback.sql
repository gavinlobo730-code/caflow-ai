-- Rollback for 407.
--
-- ⚠️ EVERY ROW IS A PAYMENT A CLIENT MADE TO THE GOVERNMENT and nothing can
-- re-derive one: the BSR code, deposit date and serial number come off a bank
-- challan the CA holds and no ledger in this product records them. Export
-- before running this:
--
--   SELECT * FROM public.self_assessment_challans;

DROP TABLE IF EXISTS public.self_assessment_challans;
