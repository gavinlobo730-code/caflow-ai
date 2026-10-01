-- Rollback for 459.
--
-- ⚠️ EVERY ROW IS A RATE SOMEBODY AGREED WITH A CUSTOMER and nothing can
-- re-derive one. Export before running this:
--
--   SELECT * FROM public.price_lists;
--   SELECT * FROM public.price_list_items;
--   SELECT id, price_list_id FROM public.customers WHERE price_list_id IS NOT NULL;
--
-- No invoice is affected: an invoice line keeps the rate it was given, and
-- nothing about a past invoice referenced these tables.

ALTER TABLE public.customers DROP COLUMN IF EXISTS price_list_id;
DROP TABLE IF EXISTS public.price_list_items;
DROP TABLE IF EXISTS public.price_lists;
