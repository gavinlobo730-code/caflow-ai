-- Migration 490 — the database asks the payroll tier, and the clients in reach, of the other payroll tables
-- (security_privacy-34, found by an independent review of migration 485; ledger POST-A-219).
--
-- THE HOLE
--   Migration 485 put the payroll role tier and the client scope into the database for payroll_employees,
--   payroll_runs, payroll_slips, attendance, leave_balances and the two declaration tables, and its header named
--   twelve payroll tables it left readable by EVERY member of the firm (one of them, reconciliation_findings, wrongly:
--   see below). The employer's bonus declaration, `bonus_declarations`, is the same kind of table and is added here.
--   They carry a firm rule (and, on most, a role tier on their writes) and nothing that asks the payroll tier or the
--   client assignment, so an Executive, a Reviewer, or a Manager the Partner has blocked from payroll could select a
--   basic salary, a loan, a perquisite, a leaver's settlement or a bonus disqualification, and on the five with no
--   write tier at all could WRITE them,
--   straight over PostgREST with their own sign-in:
--     employee-keyed   payroll_salary_revisions, payroll_loans, payroll_loan_recoveries, payroll_perquisites,
--                      payroll_one_time_earnings, payroll_settlements, bonus_disqualifications
--     parent-keyed     payroll_settlement_components (through its settlement), payroll_run_transitions (through its run)
--     client-keyed     salary_structures, statutory_remittances, epfo_ecr_filings, bonus_declarations
--   The API reserves all of it to `payroll:read` / `payroll:write` (Manager and above). The write side was
--   unguarded outright on salary_structures, bonus_declarations, bonus_disqualifications, statutory_remittances and
--   epfo_ecr_filings (a firm policy and nothing else) and on the INSERT of payroll_run_transitions.
--
-- WHO READS THESE TODAY, SO THAT NOTHING GOES QUIETLY EMPTY (read-only audit of 14-10-2026)
--   Nothing in the product reads or writes any of them under a caller's own sign-in. The payroll router is
--   built on the service client (`db_provider.service_db_or_none`), and so are the services it hands that client to
--   (the ECR filing, the statutory remittance and the bonus register), the Form 24Q and annexure builders, the
--   scheduler and the employee portal's TDS projection. The web app has no `.from("<one of them>")`. So these policies
--   bind only a direct call with a person's own JWT, which is the threat, and no Python had to change first. An
--   employee principal reads none of them under their own sign-in either (no permissive rule admits one: every rule
--   is `firm_id = get_my_firm_id()`, which is NULL for someone with no `users` row), so no own-record branch is
--   needed; if one is ever added it passes `payroll_employees`' rule, which includes the employee's own id.
--
--   ⚠️ LATENT, AND WORTH KNOWING BEFORE ANYONE MOVES A READER ONTO THE CALLER'S SIGN-IN. Several of those readers
--   answer EMPTY on failure by design: the salary in force (an empty answer pays everyone their current master rate),
--   the loan instalments of a run (an empty answer recovers nothing), the perquisites of a run (an empty answer drops
--   them from the section 192 estimate), and the transition log and loan-movement log swallow an insert failure.
--   Row security that filtered every row would be indistinguishable from "none exist" there. That is why the
--   router stays on the service role, and the comment at the top of the payroll router records it.
--
-- WHAT THIS DOES (all RESTRICTIVE, so they AND with the existing firm, assignment and role rules and can only narrow)
--   Role is asked through `my_permission(resource, action, floor)`, the function the route's `rbac()` resolves
--   through, so a per-person grant or denial in the access grid (403/415) counts here as it does at the route.
--
--   employee-keyed (7)         <table>_employee_in_reach   FOR ALL   employee_id IN (SELECT id FROM payroll_employees)
--                              <table>_write_tier_*        INSERT, UPDATE, DELETE   my_permission('payroll','write','Manager')
--   payroll_settlement_components   _settlement_in_reach   FOR ALL   settlement_id IN (SELECT id FROM payroll_settlements)
--                              plus the same write tier
--   payroll_run_transitions    _run_in_reach               FOR ALL   run_id IN (SELECT id FROM payroll_runs)
--                              plus the write tier on INSERT (UPDATE and DELETE are revoked since 328)
--   salary_structures, statutory_remittances, epfo_ecr_filings, bonus_declarations
--                              <table>_read_tier           SELECT    my_permission('payroll','read','Manager')
--                                                                    AND can_access_client(client_id)
--                                                                    AND the internal practice client is Partner-only
--                              <table>_write_tier_*        INSERT, UPDATE (and DELETE on salary_structures: the other
--                                                          two have DELETE revoked; bonus_declarations has all
--                                                          three) my_permission('payroll','write',
--                                                          'Manager') AND the same client conditions
--
--   THE FIRST TWO KINDS ARE SCOPED THROUGH THE PARENT, not through a copied client_id, for the reason 485 gives: a
--   policy expression's subquery runs under the caller's own row security, so `employee_id IN (SELECT id FROM
--   payroll_employees)` means exactly "an employee this person is allowed to see" — the payroll tier, the assignment
--   scope, the internal client's Partner-only rule and an employee's own record all come with it, with no second copy
--   of any of them to drift. The write tier is a separate policy because the parent rule asks the READ tier: a
--   person denied payroll:write but allowed payroll:read would otherwise pass it, and the existing write policies on
--   these tables ask the role (`my_role_at_least`) and not the grid.
--
--   THE LAST THREE ARE KEYED ON THE CLIENT AND NOT ON THE RUN, and that is the correction to the plan this
--   migration started from. `salary_structures` is a client template with only a client_id. `statutory_remittances`
--   and `epfo_ecr_filings` carry a client_id and a NULLABLE run_id (`ON DELETE SET NULL`; a remittance is recorded
--   without a run, and a run that is deleted leaves its filings behind). A rule that scoped them through
--   `run_id IN (SELECT id FROM payroll_runs)` would hide every remittance or filing recorded without a run, and
--   `OR run_id IS NULL` would be a hole. Scoping salary_structures through employees would hide the template of a
--   client that has no employees yet.
--
-- WHAT IT LEAVES ALONE, AND SAYS SO
--   * `reconciliation_findings` IS NOT A PAYROLL TABLE and migration 485's header lists it wrongly. Its run_id
--     points at `reconciliation_runs`, not `payroll_runs`; a run-scoped rule would leave it permanently empty for
--     everyone. It is already readable by a Partner of the firm only, and `authenticated` is granted SELECT only
--     (244). It is untouched. (Migration 485's text is not edited: a migration's checksum is what production matches on,
--     and editing one re-runs it there.)
--   * attendance, leave_balances and the two declaration tables still ask the ROLE and not the grid for WRITES (485
--     scoped their READS only), so a Manager denied payroll:write can still write them, and a grid-granted Executive
--     passes the web gate and is refused at the leave upsert. That is its own ledger line, not this migration.
--   * `salary_slips`, a view over payroll_slips and payroll_runs with security_invoker, inherits the policies of both
--     and needs no change.
--   * No function, grant, table or row changes. No backfill.
--   * The policies run a subquery against payroll_employees (whose own rule calls a plpgsql function) once per
--     statement, as 485's four children do. Nothing reads these tables under a caller's sign-in today, so there is no
--     live cost; measure it on a large firm before any reader moves.
--
-- Idempotent: DROP POLICY IF EXISTS before each CREATE, and the closing check fails the migration (and so the
-- deploy) if any policy is missing or not RESTRICTIVE. Reversible: 490_..._rollback.sql drops them again, which
-- RE-OPENS the holes.

-- ── payroll_salary_revisions ────────────────────────────────────────────────
DROP POLICY IF EXISTS "payroll_salary_revisions_employee_in_reach" ON public.payroll_salary_revisions;
CREATE POLICY "payroll_salary_revisions_employee_in_reach" ON public.payroll_salary_revisions
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (employee_id IN (SELECT e.id FROM public.payroll_employees e))
  WITH CHECK (employee_id IN (SELECT e.id FROM public.payroll_employees e));

DROP POLICY IF EXISTS "payroll_salary_revisions_write_tier_insert" ON public.payroll_salary_revisions;
CREATE POLICY "payroll_salary_revisions_write_tier_insert" ON public.payroll_salary_revisions
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('payroll', 'write', 'Manager'));

DROP POLICY IF EXISTS "payroll_salary_revisions_write_tier_update" ON public.payroll_salary_revisions;
CREATE POLICY "payroll_salary_revisions_write_tier_update" ON public.payroll_salary_revisions
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('payroll', 'write', 'Manager'))
  WITH CHECK (public.my_permission('payroll', 'write', 'Manager'));

DROP POLICY IF EXISTS "payroll_salary_revisions_write_tier_delete" ON public.payroll_salary_revisions;
CREATE POLICY "payroll_salary_revisions_write_tier_delete" ON public.payroll_salary_revisions
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('payroll', 'write', 'Manager'));

-- ── payroll_loans ───────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "payroll_loans_employee_in_reach" ON public.payroll_loans;
CREATE POLICY "payroll_loans_employee_in_reach" ON public.payroll_loans
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (employee_id IN (SELECT e.id FROM public.payroll_employees e))
  WITH CHECK (employee_id IN (SELECT e.id FROM public.payroll_employees e));

DROP POLICY IF EXISTS "payroll_loans_write_tier_insert" ON public.payroll_loans;
CREATE POLICY "payroll_loans_write_tier_insert" ON public.payroll_loans
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('payroll', 'write', 'Manager'));

DROP POLICY IF EXISTS "payroll_loans_write_tier_update" ON public.payroll_loans;
CREATE POLICY "payroll_loans_write_tier_update" ON public.payroll_loans
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('payroll', 'write', 'Manager'))
  WITH CHECK (public.my_permission('payroll', 'write', 'Manager'));

DROP POLICY IF EXISTS "payroll_loans_write_tier_delete" ON public.payroll_loans;
CREATE POLICY "payroll_loans_write_tier_delete" ON public.payroll_loans
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('payroll', 'write', 'Manager'));

-- ── payroll_loan_recoveries ─────────────────────────────────────────────────
DROP POLICY IF EXISTS "payroll_loan_recoveries_employee_in_reach" ON public.payroll_loan_recoveries;
CREATE POLICY "payroll_loan_recoveries_employee_in_reach" ON public.payroll_loan_recoveries
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (employee_id IN (SELECT e.id FROM public.payroll_employees e))
  WITH CHECK (employee_id IN (SELECT e.id FROM public.payroll_employees e));

DROP POLICY IF EXISTS "payroll_loan_recoveries_write_tier_insert" ON public.payroll_loan_recoveries;
CREATE POLICY "payroll_loan_recoveries_write_tier_insert" ON public.payroll_loan_recoveries
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('payroll', 'write', 'Manager'));

DROP POLICY IF EXISTS "payroll_loan_recoveries_write_tier_update" ON public.payroll_loan_recoveries;
CREATE POLICY "payroll_loan_recoveries_write_tier_update" ON public.payroll_loan_recoveries
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('payroll', 'write', 'Manager'))
  WITH CHECK (public.my_permission('payroll', 'write', 'Manager'));

DROP POLICY IF EXISTS "payroll_loan_recoveries_write_tier_delete" ON public.payroll_loan_recoveries;
CREATE POLICY "payroll_loan_recoveries_write_tier_delete" ON public.payroll_loan_recoveries
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('payroll', 'write', 'Manager'));

-- ── payroll_perquisites ─────────────────────────────────────────────────────
DROP POLICY IF EXISTS "payroll_perquisites_employee_in_reach" ON public.payroll_perquisites;
CREATE POLICY "payroll_perquisites_employee_in_reach" ON public.payroll_perquisites
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (employee_id IN (SELECT e.id FROM public.payroll_employees e))
  WITH CHECK (employee_id IN (SELECT e.id FROM public.payroll_employees e));

DROP POLICY IF EXISTS "payroll_perquisites_write_tier_insert" ON public.payroll_perquisites;
CREATE POLICY "payroll_perquisites_write_tier_insert" ON public.payroll_perquisites
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('payroll', 'write', 'Manager'));

DROP POLICY IF EXISTS "payroll_perquisites_write_tier_update" ON public.payroll_perquisites;
CREATE POLICY "payroll_perquisites_write_tier_update" ON public.payroll_perquisites
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('payroll', 'write', 'Manager'))
  WITH CHECK (public.my_permission('payroll', 'write', 'Manager'));

DROP POLICY IF EXISTS "payroll_perquisites_write_tier_delete" ON public.payroll_perquisites;
CREATE POLICY "payroll_perquisites_write_tier_delete" ON public.payroll_perquisites
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('payroll', 'write', 'Manager'));

-- ── payroll_one_time_earnings ───────────────────────────────────────────────
DROP POLICY IF EXISTS "payroll_one_time_earnings_employee_in_reach" ON public.payroll_one_time_earnings;
CREATE POLICY "payroll_one_time_earnings_employee_in_reach" ON public.payroll_one_time_earnings
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (employee_id IN (SELECT e.id FROM public.payroll_employees e))
  WITH CHECK (employee_id IN (SELECT e.id FROM public.payroll_employees e));

DROP POLICY IF EXISTS "payroll_one_time_earnings_write_tier_insert" ON public.payroll_one_time_earnings;
CREATE POLICY "payroll_one_time_earnings_write_tier_insert" ON public.payroll_one_time_earnings
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('payroll', 'write', 'Manager'));

DROP POLICY IF EXISTS "payroll_one_time_earnings_write_tier_update" ON public.payroll_one_time_earnings;
CREATE POLICY "payroll_one_time_earnings_write_tier_update" ON public.payroll_one_time_earnings
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('payroll', 'write', 'Manager'))
  WITH CHECK (public.my_permission('payroll', 'write', 'Manager'));

DROP POLICY IF EXISTS "payroll_one_time_earnings_write_tier_delete" ON public.payroll_one_time_earnings;
CREATE POLICY "payroll_one_time_earnings_write_tier_delete" ON public.payroll_one_time_earnings
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('payroll', 'write', 'Manager'));

-- ── payroll_settlements ─────────────────────────────────────────────────────
DROP POLICY IF EXISTS "payroll_settlements_employee_in_reach" ON public.payroll_settlements;
CREATE POLICY "payroll_settlements_employee_in_reach" ON public.payroll_settlements
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (employee_id IN (SELECT e.id FROM public.payroll_employees e))
  WITH CHECK (employee_id IN (SELECT e.id FROM public.payroll_employees e));

DROP POLICY IF EXISTS "payroll_settlements_write_tier_insert" ON public.payroll_settlements;
CREATE POLICY "payroll_settlements_write_tier_insert" ON public.payroll_settlements
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('payroll', 'write', 'Manager'));

DROP POLICY IF EXISTS "payroll_settlements_write_tier_update" ON public.payroll_settlements;
CREATE POLICY "payroll_settlements_write_tier_update" ON public.payroll_settlements
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('payroll', 'write', 'Manager'))
  WITH CHECK (public.my_permission('payroll', 'write', 'Manager'));

DROP POLICY IF EXISTS "payroll_settlements_write_tier_delete" ON public.payroll_settlements;
CREATE POLICY "payroll_settlements_write_tier_delete" ON public.payroll_settlements
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('payroll', 'write', 'Manager'));

-- ── bonus_disqualifications ─────────────────────────────────────────────────
DROP POLICY IF EXISTS "bonus_disqualifications_employee_in_reach" ON public.bonus_disqualifications;
CREATE POLICY "bonus_disqualifications_employee_in_reach" ON public.bonus_disqualifications
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (employee_id IN (SELECT e.id FROM public.payroll_employees e))
  WITH CHECK (employee_id IN (SELECT e.id FROM public.payroll_employees e));

DROP POLICY IF EXISTS "bonus_disqualifications_write_tier_insert" ON public.bonus_disqualifications;
CREATE POLICY "bonus_disqualifications_write_tier_insert" ON public.bonus_disqualifications
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('payroll', 'write', 'Manager'));

DROP POLICY IF EXISTS "bonus_disqualifications_write_tier_update" ON public.bonus_disqualifications;
CREATE POLICY "bonus_disqualifications_write_tier_update" ON public.bonus_disqualifications
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('payroll', 'write', 'Manager'))
  WITH CHECK (public.my_permission('payroll', 'write', 'Manager'));

DROP POLICY IF EXISTS "bonus_disqualifications_write_tier_delete" ON public.bonus_disqualifications;
CREATE POLICY "bonus_disqualifications_write_tier_delete" ON public.bonus_disqualifications
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('payroll', 'write', 'Manager'));

-- ── payroll_settlement_components ───────────────────────────────────────────
DROP POLICY IF EXISTS "payroll_settlement_components_settlement_in_reach" ON public.payroll_settlement_components;
CREATE POLICY "payroll_settlement_components_settlement_in_reach" ON public.payroll_settlement_components
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (settlement_id IN (SELECT s.id FROM public.payroll_settlements s))
  WITH CHECK (settlement_id IN (SELECT s.id FROM public.payroll_settlements s));

DROP POLICY IF EXISTS "payroll_settlement_components_write_tier_insert" ON public.payroll_settlement_components;
CREATE POLICY "payroll_settlement_components_write_tier_insert" ON public.payroll_settlement_components
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('payroll', 'write', 'Manager'));

DROP POLICY IF EXISTS "payroll_settlement_components_write_tier_update" ON public.payroll_settlement_components;
CREATE POLICY "payroll_settlement_components_write_tier_update" ON public.payroll_settlement_components
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('payroll', 'write', 'Manager'))
  WITH CHECK (public.my_permission('payroll', 'write', 'Manager'));

DROP POLICY IF EXISTS "payroll_settlement_components_write_tier_delete" ON public.payroll_settlement_components;
CREATE POLICY "payroll_settlement_components_write_tier_delete" ON public.payroll_settlement_components
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('payroll', 'write', 'Manager'));

-- ── payroll_run_transitions ─────────────────────────────────────────────────
DROP POLICY IF EXISTS "payroll_run_transitions_run_in_reach" ON public.payroll_run_transitions;
CREATE POLICY "payroll_run_transitions_run_in_reach" ON public.payroll_run_transitions
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (run_id IN (SELECT r.id FROM public.payroll_runs r))
  WITH CHECK (run_id IN (SELECT r.id FROM public.payroll_runs r));

DROP POLICY IF EXISTS "payroll_run_transitions_write_tier_insert" ON public.payroll_run_transitions;
CREATE POLICY "payroll_run_transitions_write_tier_insert" ON public.payroll_run_transitions
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('payroll', 'write', 'Manager'));

-- ── salary_structures ───────────────────────────────────────────────────────
DROP POLICY IF EXISTS "salary_structures_read_tier" ON public.salary_structures;
CREATE POLICY "salary_structures_read_tier" ON public.salary_structures
  AS RESTRICTIVE FOR SELECT TO authenticated
  USING (public.my_permission('payroll', 'read', 'Manager') AND public.can_access_client(client_id::text) AND (public.get_my_role() = 'Partner' OR client_id::text IS DISTINCT FROM public.my_internal_client_id()::text));

DROP POLICY IF EXISTS "salary_structures_write_tier_insert" ON public.salary_structures;
CREATE POLICY "salary_structures_write_tier_insert" ON public.salary_structures
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('payroll', 'write', 'Manager') AND public.can_access_client(client_id::text) AND (public.get_my_role() = 'Partner' OR client_id::text IS DISTINCT FROM public.my_internal_client_id()::text));

DROP POLICY IF EXISTS "salary_structures_write_tier_update" ON public.salary_structures;
CREATE POLICY "salary_structures_write_tier_update" ON public.salary_structures
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('payroll', 'write', 'Manager') AND public.can_access_client(client_id::text) AND (public.get_my_role() = 'Partner' OR client_id::text IS DISTINCT FROM public.my_internal_client_id()::text))
  WITH CHECK (public.my_permission('payroll', 'write', 'Manager') AND public.can_access_client(client_id::text) AND (public.get_my_role() = 'Partner' OR client_id::text IS DISTINCT FROM public.my_internal_client_id()::text));

DROP POLICY IF EXISTS "salary_structures_write_tier_delete" ON public.salary_structures;
CREATE POLICY "salary_structures_write_tier_delete" ON public.salary_structures
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('payroll', 'write', 'Manager') AND public.can_access_client(client_id::text) AND (public.get_my_role() = 'Partner' OR client_id::text IS DISTINCT FROM public.my_internal_client_id()::text));

-- ── statutory_remittances ───────────────────────────────────────────────────
DROP POLICY IF EXISTS "statutory_remittances_read_tier" ON public.statutory_remittances;
CREATE POLICY "statutory_remittances_read_tier" ON public.statutory_remittances
  AS RESTRICTIVE FOR SELECT TO authenticated
  USING (public.my_permission('payroll', 'read', 'Manager') AND public.can_access_client(client_id::text) AND (public.get_my_role() = 'Partner' OR client_id::text IS DISTINCT FROM public.my_internal_client_id()::text));

DROP POLICY IF EXISTS "statutory_remittances_write_tier_insert" ON public.statutory_remittances;
CREATE POLICY "statutory_remittances_write_tier_insert" ON public.statutory_remittances
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('payroll', 'write', 'Manager') AND public.can_access_client(client_id::text) AND (public.get_my_role() = 'Partner' OR client_id::text IS DISTINCT FROM public.my_internal_client_id()::text));

DROP POLICY IF EXISTS "statutory_remittances_write_tier_update" ON public.statutory_remittances;
CREATE POLICY "statutory_remittances_write_tier_update" ON public.statutory_remittances
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('payroll', 'write', 'Manager') AND public.can_access_client(client_id::text) AND (public.get_my_role() = 'Partner' OR client_id::text IS DISTINCT FROM public.my_internal_client_id()::text))
  WITH CHECK (public.my_permission('payroll', 'write', 'Manager') AND public.can_access_client(client_id::text) AND (public.get_my_role() = 'Partner' OR client_id::text IS DISTINCT FROM public.my_internal_client_id()::text));

-- ── epfo_ecr_filings ────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "epfo_ecr_filings_read_tier" ON public.epfo_ecr_filings;
CREATE POLICY "epfo_ecr_filings_read_tier" ON public.epfo_ecr_filings
  AS RESTRICTIVE FOR SELECT TO authenticated
  USING (public.my_permission('payroll', 'read', 'Manager') AND public.can_access_client(client_id::text) AND (public.get_my_role() = 'Partner' OR client_id::text IS DISTINCT FROM public.my_internal_client_id()::text));

DROP POLICY IF EXISTS "epfo_ecr_filings_write_tier_insert" ON public.epfo_ecr_filings;
CREATE POLICY "epfo_ecr_filings_write_tier_insert" ON public.epfo_ecr_filings
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('payroll', 'write', 'Manager') AND public.can_access_client(client_id::text) AND (public.get_my_role() = 'Partner' OR client_id::text IS DISTINCT FROM public.my_internal_client_id()::text));

DROP POLICY IF EXISTS "epfo_ecr_filings_write_tier_update" ON public.epfo_ecr_filings;
CREATE POLICY "epfo_ecr_filings_write_tier_update" ON public.epfo_ecr_filings
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('payroll', 'write', 'Manager') AND public.can_access_client(client_id::text) AND (public.get_my_role() = 'Partner' OR client_id::text IS DISTINCT FROM public.my_internal_client_id()::text))
  WITH CHECK (public.my_permission('payroll', 'write', 'Manager') AND public.can_access_client(client_id::text) AND (public.get_my_role() = 'Partner' OR client_id::text IS DISTINCT FROM public.my_internal_client_id()::text));

-- ── bonus_declarations ──────────────────────────────────────────────────────
DROP POLICY IF EXISTS "bonus_declarations_read_tier" ON public.bonus_declarations;
CREATE POLICY "bonus_declarations_read_tier" ON public.bonus_declarations
  AS RESTRICTIVE FOR SELECT TO authenticated
  USING (public.my_permission('payroll', 'read', 'Manager') AND public.can_access_client(client_id::text) AND (public.get_my_role() = 'Partner' OR client_id::text IS DISTINCT FROM public.my_internal_client_id()::text));

DROP POLICY IF EXISTS "bonus_declarations_write_tier_insert" ON public.bonus_declarations;
CREATE POLICY "bonus_declarations_write_tier_insert" ON public.bonus_declarations
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('payroll', 'write', 'Manager') AND public.can_access_client(client_id::text) AND (public.get_my_role() = 'Partner' OR client_id::text IS DISTINCT FROM public.my_internal_client_id()::text));

DROP POLICY IF EXISTS "bonus_declarations_write_tier_update" ON public.bonus_declarations;
CREATE POLICY "bonus_declarations_write_tier_update" ON public.bonus_declarations
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('payroll', 'write', 'Manager') AND public.can_access_client(client_id::text) AND (public.get_my_role() = 'Partner' OR client_id::text IS DISTINCT FROM public.my_internal_client_id()::text))
  WITH CHECK (public.my_permission('payroll', 'write', 'Manager') AND public.can_access_client(client_id::text) AND (public.get_my_role() = 'Partner' OR client_id::text IS DISTINCT FROM public.my_internal_client_id()::text));

DROP POLICY IF EXISTS "bonus_declarations_write_tier_delete" ON public.bonus_declarations;
CREATE POLICY "bonus_declarations_write_tier_delete" ON public.bonus_declarations
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('payroll', 'write', 'Manager') AND public.can_access_client(client_id::text) AND (public.get_my_role() = 'Partner' OR client_id::text IS DISTINCT FROM public.my_internal_client_id()::text));

-- ── the closing check: all 48 policies exist and every one is RESTRICTIVE ───────────────────────
DO $$
DECLARE
  n int;
BEGIN
  SELECT count(*) INTO n
    FROM pg_policies
   WHERE schemaname = 'public'
     AND permissive = 'RESTRICTIVE'
     AND policyname IN (
       'payroll_salary_revisions_employee_in_reach',
       'payroll_salary_revisions_write_tier_insert',
       'payroll_salary_revisions_write_tier_update',
       'payroll_salary_revisions_write_tier_delete',
       'payroll_loans_employee_in_reach',
       'payroll_loans_write_tier_insert',
       'payroll_loans_write_tier_update',
       'payroll_loans_write_tier_delete',
       'payroll_loan_recoveries_employee_in_reach',
       'payroll_loan_recoveries_write_tier_insert',
       'payroll_loan_recoveries_write_tier_update',
       'payroll_loan_recoveries_write_tier_delete',
       'payroll_perquisites_employee_in_reach',
       'payroll_perquisites_write_tier_insert',
       'payroll_perquisites_write_tier_update',
       'payroll_perquisites_write_tier_delete',
       'payroll_one_time_earnings_employee_in_reach',
       'payroll_one_time_earnings_write_tier_insert',
       'payroll_one_time_earnings_write_tier_update',
       'payroll_one_time_earnings_write_tier_delete',
       'payroll_settlements_employee_in_reach',
       'payroll_settlements_write_tier_insert',
       'payroll_settlements_write_tier_update',
       'payroll_settlements_write_tier_delete',
       'bonus_disqualifications_employee_in_reach',
       'bonus_disqualifications_write_tier_insert',
       'bonus_disqualifications_write_tier_update',
       'bonus_disqualifications_write_tier_delete',
       'payroll_settlement_components_settlement_in_reach',
       'payroll_settlement_components_write_tier_insert',
       'payroll_settlement_components_write_tier_update',
       'payroll_settlement_components_write_tier_delete',
       'payroll_run_transitions_run_in_reach',
       'payroll_run_transitions_write_tier_insert',
       'salary_structures_read_tier',
       'salary_structures_write_tier_insert',
       'salary_structures_write_tier_update',
       'salary_structures_write_tier_delete',
       'statutory_remittances_read_tier',
       'statutory_remittances_write_tier_insert',
       'statutory_remittances_write_tier_update',
       'epfo_ecr_filings_read_tier',
       'epfo_ecr_filings_write_tier_insert',
       'epfo_ecr_filings_write_tier_update',
       'bonus_declarations_read_tier',
       'bonus_declarations_write_tier_insert',
       'bonus_declarations_write_tier_update',
       'bonus_declarations_write_tier_delete');
  IF n <> 48 THEN
    RAISE EXCEPTION 'migration 490: expected 48 restrictive policies, found %', n;
  END IF;
END $$;
