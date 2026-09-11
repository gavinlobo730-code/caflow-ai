-- Rollback for 368.
ALTER TABLE public.payroll_slips
  DROP CONSTRAINT IF EXISTS payroll_slips_perquisites_nonneg;
ALTER TABLE public.payroll_slips
  DROP COLUMN IF EXISTS perquisites_in_tds_estimate_paise;
