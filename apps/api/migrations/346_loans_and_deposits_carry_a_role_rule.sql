-- ============================================================================
-- 346 — a client's borrowings and deposits carry a role rule
--
-- WHAT WAS WRONG
--     app/accounting/loans/page.tsx inserts into public.loans and
--     public.fixed_deposits straight from the browser over PostgREST. rbac()
--     does not run on that path, so RLS is the only check — and while both
--     tables DO carry an assignment rule (loans_assignment_scope /
--     fixed_deposits_assignment_scope, `can_access_client(client_id)`), neither
--     carries a ROLE rule.
--
--     So a Reviewer — read/approve-only by design in core/permissions.py's
--     Partner > Manager > Executive > Reviewer > Client ladder, and the role
--     the legacy 'viewer' maps to — could add or alter a client's loan
--     principal, outstanding balance, interest rate or EMI, provided they were
--     assigned to that client. Those figures are a balance-sheet liability and
--     they feed the risk screen and the cash-flow report.
--
--     Migrations 260 and 261 added this rule to twenty-three tables and 345 to
--     the four TDS ones. These two were missed because the scan that finds
--     browser writes could not see a statement longer than 400 characters —
--     fixed in tests/test_direct_write_tables_are_role_guarded.py, which is
--     what surfaced them.
--
-- THE TIER, AND WHOSE DECISION IT WAS
--     Executive for INSERT, UPDATE and DELETE alike — an owner decision of
--     2026-09-09, not a copied one, because these two tables have no API
--     endpoint whose rbac() guard could be mirrored. The reasoning given:
--     a client handed to an Executive is that Executive's to run, so they must
--     be able to record and correct its borrowings without escalating.
--
--     That is narrower than it sounds, because the ASSIGNMENT rule is already
--     in force: an Executive reaches only the clients in
--     user_client_assignments. What this migration changes is not which clients
--     a person can touch — it is that a Reviewer assigned to a client can no
--     longer WRITE its loans, only read them.
--
--     DELETE is deliberately NOT raised to Manager here, though 260's default
--     would allow it. Splitting the tiers would mean an Executive could enter a
--     loan and then need a Manager to undo their own typo, which is the kind of
--     rule that gets worked around rather than followed.
--
-- WHAT THIS DOES NOT FIX
--     A delete over PostgREST still writes no audit_log row, because log_event
--     only runs on the API path. The role rule stops a Reviewer; it cannot
--     record what a legitimate Executive removed. Closing that means giving
--     these tables a real endpoint, the way the TDS register got one in
--     Phase 3b. Recorded in the phase plan rather than half-done here.
--
-- RESTRICTIVE and PER COMMAND, for the same two reasons as 260, 261 and 345:
-- the existing firm policy is PERMISSIVE and would OR with a permissive
-- addition (widening access while reading like a tightening), and a
-- RESTRICTIVE ... FOR ALL rule would apply its USING to SELECT, stopping a
-- Reviewer READING a loan they are entitled to see.
-- ============================================================================

DO $$
DECLARE
  -- (table, minimum role for INSERT/UPDATE, minimum role for DELETE)
  pol  text[][] := ARRAY[
    ['loans',          'Executive', 'Executive'],
    ['fixed_deposits', 'Executive', 'Executive']
  ];
  t         text;
  min_write text;
  min_del   text;
  i         int;
BEGIN
  FOR i IN 1 .. array_length(pol, 1) LOOP
    t         := pol[i][1];
    min_write := pol[i][2];
    min_del   := pol[i][3];

    IF to_regclass('public.' || quote_ident(t)) IS NULL THEN
      RAISE NOTICE 'migration 346: skipping %, table not present', t;
      CONTINUE;
    END IF;

    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_insert', t);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR INSERT '
      'WITH CHECK (public.my_role_at_least(%L))',
      t || '_role_insert', t, min_write);

    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_update', t);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR UPDATE '
      'USING (public.my_role_at_least(%L)) WITH CHECK (public.my_role_at_least(%L))',
      t || '_role_update', t, min_write, min_write);

    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_delete', t);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR DELETE '
      'USING (public.my_role_at_least(%L))',
      t || '_role_delete', t, min_del);
  END LOOP;
END $$;
