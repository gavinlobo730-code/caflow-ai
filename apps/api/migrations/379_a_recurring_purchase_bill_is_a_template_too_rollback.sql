-- Rollback for migration 379.
--
-- The two columns on `purchase_bills` are dropped LAST, after the tables that
-- reference them, and the unique index with them. Every generated bill
-- survives: it is an ordinary purchase bill and loses only the link back to
-- the template that suggested it.
DROP INDEX IF EXISTS public.uq_purchase_bills_recurring;
DROP TABLE IF EXISTS public.recurring_purchase_bill_runs;
DROP TABLE IF EXISTS public.recurring_purchase_bill_template_lines;
ALTER TABLE public.purchase_bills DROP COLUMN IF EXISTS recurring_template_id;
ALTER TABLE public.purchase_bills DROP COLUMN IF EXISTS recurring_occurrence;
DROP TABLE IF EXISTS public.recurring_purchase_bill_templates;
