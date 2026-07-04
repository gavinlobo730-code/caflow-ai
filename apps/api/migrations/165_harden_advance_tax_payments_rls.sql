-- Migration 165: harden advance_tax_payments RLS -- move all mutation to the
-- backend service-role path (routers/income_tax.py's new /advance-tax
-- endpoints), matching the R3.0/R3.1b pattern for client_portal_users and
-- capital_gains.
--
-- Migration 035's firm_staff_manage_advance_tax policy was FOR ALL, scoped
-- only by firm_id -- combined with a table-level GRANT INSERT/UPDATE/DELETE
-- TO authenticated, any authenticated firm staff member could directly
-- write an advance_tax_payments row from the browser with a self-reported
-- paid_amount_paise/due_date/required_percent, bypassing the Section 234C
-- engine entirely (R3.13a).

REVOKE INSERT, UPDATE, DELETE ON public.advance_tax_payments FROM authenticated;

DROP POLICY IF EXISTS "firm_staff_manage_advance_tax" ON public.advance_tax_payments;
CREATE POLICY "firm_staff_manage_advance_tax" ON public.advance_tax_payments
  FOR SELECT TO authenticated
  USING (firm_id = public.get_my_firm_id());
