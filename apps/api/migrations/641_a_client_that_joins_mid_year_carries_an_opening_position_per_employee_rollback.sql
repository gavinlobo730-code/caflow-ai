-- Rollback for migration 641. Drops the table and the opening positions in it; the §192 spread then reads released runs only,
-- as it did before, which over-deducts (the safe direction) for a mid-year client.
DROP TABLE IF EXISTS public.payroll_opening_positions;
