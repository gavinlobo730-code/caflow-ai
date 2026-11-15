-- Rollback of migration 594: drops the two vendor triggers the shared guard added for the column, the index, the CHECK and the column. A
-- typed deduction then carries its name and PAN only, as before; nothing else is lost (the tax and the amounts stay on the rows). The
-- triggers go first because the update trigger names the column (UPDATE OF ... vendor_id), which blocks dropping it. The client-in-firm
-- triggers the guard re-created are the ones the table had before 594 and stay. Safe to run twice.
DROP TRIGGER IF EXISTS row_vendor_in_client_ins ON public.tds_deductions;
DROP TRIGGER IF EXISTS row_vendor_in_client_upd ON public.tds_deductions;
DROP INDEX IF EXISTS public.idx_tds_deductions_typed_supplier;
ALTER TABLE public.tds_deductions DROP CONSTRAINT IF EXISTS tds_deductions_supplier_only_on_a_typed_row;
ALTER TABLE public.tds_deductions DROP COLUMN IF EXISTS vendor_id;
