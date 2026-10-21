-- Migration 531 — the statutory identity, the payroll settings and the PT registrations of a client take the client's
-- assignment scope and the internal practice's Partner-only guard (POST-A-299, second tranche: the three tables the ledger
-- item named first, because the first of them holds the TAN and the statutory identifiers).
--
-- THE HOLE
--
--   Each table carries a NOT NULL `client_id` and a firm policy (`firm_id = get_my_firm_id()`) and, for writes, a role tier
--   (Manager and above). Nothing asks which CLIENT. Migration 084 gave the client tables of its day a
--   RESTRICTIVE assignment scope and 074 the internal practice's Partner-only guard; these three were created afterwards on
--   the premise that "nothing reaches them from the browser and the backend bypasses row security", which is false in the
--   same two ways migrations 527 to 529 record: PostgREST answers for every table the signed-in role is granted, and the API
--   reads some of them under the CALLER's sign-in when USE_USER_JWT is on, the production default. Migration 519 took every
--   write away from the signed-in role (they are written by the API alone, with the service role), so what is open is the
--   READ, to every member of the firm whatever clients they are assigned to and whatever their role (a Reviewer included):
--
--       client_statutory_identity   the client's TAN, EPF establishment code, ESIC employer code and LIN: the identifiers a
--                                   TDS statement and a payslip are filed and printed under
--       client_payroll_settings     whether payroll is switched on for the client, who switched it on and when, and the day
--                                   its inputs are due
--       client_pt_registrations     the client's professional-tax certificate numbers (PTRC, PTEC) by state
--
--   A member assigned to no client, or to a different one, could list all three for every client of the firm, and the
--   internal practice's own (a Partner's, by 074).
--
-- WHAT THIS DOES
--
--   On each of the three, the two RESTRICTIVE FOR ALL policies the other client tables carry, written the way migrations 525
--   to 529 write them so that they are asked once per query and not once per row:
--
--       <table>_assignment_scope       COALESCE(client_id::text IS NULL OR (SELECT get_my_role()) = 'Partner'
--                                               OR client_id::text IN (SELECT my_assigned_client_ids()), false)
--       <table>_internal_partner_only  (SELECT get_my_role()) = 'Partner'
--                                      OR client_id::text IS DISTINCT FROM (SELECT my_internal_client_id())::text
--
--   in the USING and in the WITH CHECK. The WITH CHECK matters less than elsewhere, because the signed-in role holds no
--   write grant on these tables since 519, but it is the second lock, and it keeps the catalog rule's definition of a
--   scoped table (a restrictive policy that asks the caller's clients, in both clauses) true of them. The client is NOT NULL
--   on all three, so the `client_id IS NULL OR` branch of the scope can never be true here; it is written anyway, because
--   every scope since 527 is written in that one shape (migration 528 carries it on its NOT NULL tables too) and the rollback
--   of migration 526 recognises only that shape: a scope without it blocks that rollback, which a first draft of this
--   migration did (the real-Postgres test of 526 failed on it). The internal-practice guard needs no such branch.
--
--   It narrows the firm policy already there and cannot widen anything. Nothing a Partner does changes. Nothing an assigned
--   Manager or Executive does for their own clients changes: every route that reaches these tables asserts the client first
--   (`routers/payroll.py`, `routers/tds.py`, the Form 3CD clause 34 and the payslip renderer), and the payroll router reads
--   and writes them with the service role anyway (`routers.payroll._db` is `service_db_or_none`), so its answers do not
--   change at all; Form 3CD clause 34 reads the TAN with the service role as well (`routers.income_tax._db`). No screen reads
--   them over PostgREST. THE TWO READS THAT RUN UNDER THE CALLER'S SIGN-IN are the deductor block of a TDS statement
--   (`routers.tds._deductor_sources`, behind the 24Q, 26Q and 27Q from-books routes and `GET /api/tds/deductor`) and the
--   employer block of the staff payslip routes (`services.payslip_pdf_service.load_employer`); both are staff reads of one
--   client the route has already checked. ONE EDGE, SAID HERE: a Manager or Executive who is assigned to the internal practice
--   passes the route's client check and then meets the practice guard on the identity row, so the deductor block reads as
--   "no TAN recorded" (their read of the `clients` row for the practice was already hidden by the same guard, so its name,
--   PAN and address read the same way); payroll is barred for the practice, so no flow loses data.
--
-- WHAT IT LEAVES ALONE, AND SAYS SO
--
--   * An employee or a portal contact never had a branch on these tables: the firm policy asks `get_my_firm_id()`, which
--     is NULL for anyone without a `users` row, so the employee portal's payslip reads the employer block with the service
--     role after proving ownership (POST-A-220, `routers/portal_employee.py`), and a test says so. There is nothing to keep
--     here.
--   * The eight client tables still on the shrink-only list `tests/fixtures/assignment_scope_exceptions.json` (kind
--     `pending`, POST-A-299): the year locks, the two FX tables, the stock ledger, the two party-credit tables, the demo
--     filings and the portal sessions.
--   * The write side. 519's REVOKE stays the control for it; a test asserts that the signed-in role still holds no
--     INSERT, UPDATE, DELETE or TRUNCATE on any of the three, so that a later GRANT shows up beside the policies.
--
-- Idempotent (DROP POLICY IF EXISTS before each CREATE). Reversible: 531_..._rollback.sql drops the six policies, which
-- restores the firm-wide read and nothing else.
--
-- LOCKS. DROP POLICY and CREATE POLICY take an ACCESS EXCLUSIVE lock on their table until the migration commits (it is one
-- transaction); the three tables are small (one row per client, and one per client and state). A lock_timeout of 15
-- seconds for this transaction (as 525 to 530 set) makes a long-running transaction that holds one of them fail the
-- migration, to be re-run, instead of queueing every later request on the table behind it.
--
-- Every CREATE POLICY below is written out with its name as a literal, on purpose: `test_guards_match_production_pg` excuses
-- a restrictive policy that production does not hold yet only when a migration after its snapshot names it in plain text.

SELECT set_config('lock_timeout', '15s', true);

-- client_statutory_identity: the client's TAN, EPF establishment code, ESIC employer code and LIN
DROP POLICY IF EXISTS "client_statutory_identity_assignment_scope" ON public.client_statutory_identity;
CREATE POLICY "client_statutory_identity_assignment_scope" ON public.client_statutory_identity
  AS RESTRICTIVE FOR ALL
  USING (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                   OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false))
  WITH CHECK (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                        OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false));

DROP POLICY IF EXISTS "client_statutory_identity_internal_partner_only" ON public.client_statutory_identity;
CREATE POLICY "client_statutory_identity_internal_partner_only" ON public.client_statutory_identity
  AS RESTRICTIVE FOR ALL
  USING ((SELECT public.get_my_role()) = 'Partner'::text
         OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
  WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
              OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

-- client_payroll_settings: whether payroll is switched on for the client, by whom and when, and its inputs-due day
DROP POLICY IF EXISTS "client_payroll_settings_assignment_scope" ON public.client_payroll_settings;
CREATE POLICY "client_payroll_settings_assignment_scope" ON public.client_payroll_settings
  AS RESTRICTIVE FOR ALL
  USING (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                   OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false))
  WITH CHECK (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                        OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false));

DROP POLICY IF EXISTS "client_payroll_settings_internal_partner_only" ON public.client_payroll_settings;
CREATE POLICY "client_payroll_settings_internal_partner_only" ON public.client_payroll_settings
  AS RESTRICTIVE FOR ALL
  USING ((SELECT public.get_my_role()) = 'Partner'::text
         OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
  WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
              OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

-- client_pt_registrations: the client's professional-tax certificate numbers, by state
DROP POLICY IF EXISTS "client_pt_registrations_assignment_scope" ON public.client_pt_registrations;
CREATE POLICY "client_pt_registrations_assignment_scope" ON public.client_pt_registrations
  AS RESTRICTIVE FOR ALL
  USING (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                   OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false))
  WITH CHECK (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                        OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false));

DROP POLICY IF EXISTS "client_pt_registrations_internal_partner_only" ON public.client_pt_registrations;
CREATE POLICY "client_pt_registrations_internal_partner_only" ON public.client_pt_registrations
  AS RESTRICTIVE FOR ALL
  USING ((SELECT public.get_my_role()) = 'Partner'::text
         OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
  WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
              OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);
