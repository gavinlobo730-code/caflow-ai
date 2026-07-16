-- Migration 212 — RLS + grants for the 6 tables migration 210 created.
--
-- Found by an independent adversarial review: migration 210 said its new
-- tables "mirror credit_notes/credit_note_lines/credit_note_allocations
-- exactly" and "mirror debit_notes/debit_note_lines/debit_note_allocations
-- exactly" — true for every column, but it missed that both of those
-- sibling pairs also carry RLS (migration 050 for credit_notes*, migration
-- 145 for debit_notes*) plus the base GRANTs migrations 192/193/194 later
-- had to add after the same mistake shipped without RLS at all (194's
-- own words: "an RLS policy is written scoped to authenticated... but the
-- base table-level GRANT for that command is never issued alongside it").
-- Migration 210 shipped with neither.
--
-- Dormant today (services/*.py all read via get_supabase(), the
-- service-role client, which bypasses RLS and grants both) — but once the
-- per-user-JWT cutover (USE_USER_JWT) flips, every read/write on these 6
-- tables would fail with "permission denied", and if a future change adds
-- grants without matching RLS first, it would be a cross-tenant exposure.
-- Same policy shape as migration 145 (debit_notes/debit_note_lines/
-- debit_note_allocations) — the sibling migration these tables actually
-- mirror row-for-row.

ALTER TABLE public.sales_debit_notes             ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sales_debit_note_lines        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sales_debit_note_allocations  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.purchase_credit_notes             ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.purchase_credit_note_lines        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.purchase_credit_note_allocations  ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS firm_sales_debit_notes ON public.sales_debit_notes;
CREATE POLICY firm_sales_debit_notes ON public.sales_debit_notes FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id()) WITH CHECK (firm_id = public.get_my_firm_id());

DROP POLICY IF EXISTS firm_sales_debit_note_lines ON public.sales_debit_note_lines;
CREATE POLICY firm_sales_debit_note_lines ON public.sales_debit_note_lines FOR ALL TO authenticated
  USING (debit_note_id IN (SELECT id FROM public.sales_debit_notes WHERE firm_id = public.get_my_firm_id()))
  WITH CHECK (debit_note_id IN (SELECT id FROM public.sales_debit_notes WHERE firm_id = public.get_my_firm_id()));

DROP POLICY IF EXISTS firm_sales_debit_note_allocations ON public.sales_debit_note_allocations;
CREATE POLICY firm_sales_debit_note_allocations ON public.sales_debit_note_allocations FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id()) WITH CHECK (firm_id = public.get_my_firm_id());

DROP POLICY IF EXISTS firm_purchase_credit_notes ON public.purchase_credit_notes;
CREATE POLICY firm_purchase_credit_notes ON public.purchase_credit_notes FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id()) WITH CHECK (firm_id = public.get_my_firm_id());

DROP POLICY IF EXISTS firm_purchase_credit_note_lines ON public.purchase_credit_note_lines;
CREATE POLICY firm_purchase_credit_note_lines ON public.purchase_credit_note_lines FOR ALL TO authenticated
  USING (credit_note_id IN (SELECT id FROM public.purchase_credit_notes WHERE firm_id = public.get_my_firm_id()))
  WITH CHECK (credit_note_id IN (SELECT id FROM public.purchase_credit_notes WHERE firm_id = public.get_my_firm_id()));

DROP POLICY IF EXISTS firm_purchase_credit_note_allocations ON public.purchase_credit_note_allocations;
CREATE POLICY firm_purchase_credit_note_allocations ON public.purchase_credit_note_allocations FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id()) WITH CHECK (firm_id = public.get_my_firm_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON public.sales_debit_notes            TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.sales_debit_note_lines       TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.sales_debit_note_allocations TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.purchase_credit_notes            TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.purchase_credit_note_lines       TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.purchase_credit_note_allocations TO authenticated;
