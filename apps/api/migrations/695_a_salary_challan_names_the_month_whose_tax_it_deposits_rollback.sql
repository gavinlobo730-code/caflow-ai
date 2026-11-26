-- Rollback of migration 695: a salary challan no longer names the wage month it deposits. Obligations already closed from it stay
-- closed, with their date and challan; only the stated months go, so no recorded salary challan closes a month again.

BEGIN;

ALTER TABLE public.tds_challans DROP CONSTRAINT IF EXISTS tds_challans_deduction_month_shape;
ALTER TABLE public.tds_challans DROP COLUMN IF EXISTS deduction_month;

COMMIT;
