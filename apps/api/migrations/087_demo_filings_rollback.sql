-- Rollback for migration 087: drop the demo_filings table.
DROP TABLE IF EXISTS public.demo_filings CASCADE;
