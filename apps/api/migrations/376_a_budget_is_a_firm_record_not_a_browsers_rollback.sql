-- Rollback for migration 376.
--
-- Drops the table, which drops every budget figure recorded through it. That
-- is the honest rollback: before 376 the figures lived in one browser's local
-- storage and there is nowhere else to put them back.
DROP TABLE IF EXISTS public.account_budgets;
