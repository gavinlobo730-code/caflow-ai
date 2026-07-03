-- 164 — Harden capital_gains RLS/grants (R3.1b).
--
-- Migration 030 created capital_gains with the same shape of gap as
-- client_portal_users (migration 109, fixed by 163) and users (migration
-- 153): a FOR ALL policy scoped only by firm_id, plus a table-level GRANT
-- INSERT/UPDATE/DELETE TO authenticated. Any authenticated firm staff
-- member could directly write a capital_gains row from the browser with
-- self-reported gain_type/tax_rate_percent/indexed_cost_paise values,
-- bypassing all server-side computation entirely.
--
-- R3.1b moves every legitimate mutation of this table onto the backend
-- (routers/income_tax.py's capital-gains endpoints, which compute
-- gain_type/indexed_cost_paise/tax_rate_percent server-side via
-- domain/income_tax/capital_gains_engine.py rather than trusting the
-- client) -- so, as with client_portal_users, there is no longer any
-- legitimate frontend write path to preserve.
REVOKE INSERT, UPDATE, DELETE ON public.capital_gains FROM authenticated;

DROP POLICY IF EXISTS "firm_staff_manage_capital_gains" ON public.capital_gains;

CREATE POLICY "firm_staff_manage_capital_gains" ON public.capital_gains
  FOR SELECT TO authenticated
  USING (firm_id = public.get_my_firm_id());
