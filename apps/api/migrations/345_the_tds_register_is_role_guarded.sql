-- ============================================================================
-- 345 — the TDS register carries a role rule, like every other table the
--       browser writes
--
-- WHAT WAS WRONG (TDS-11)
--     tds_deductions and tds_returns are written straight from the browser
--     over PostgREST (apps/web/app/tds/page.tsx, apps/web/lib/data/tds.ts).
--     rbac() does not run on that path — CLAUDE.md is explicit that RLS is the
--     only check there — and the RLS on all four TDS tables is firm-scoped
--     with NO role predicate:
--
--         014_complete_missing_tables.sql   tds_deductions_own_firm
--             FOR ALL USING (firm_id = get_my_firm_id())
--         037_tds_engine.sql                the same shape for the other three
--         041_grant_all_tables_to_authenticated.sql
--             GRANT SELECT, INSERT, UPDATE, DELETE ... TO authenticated
--
--     So any authenticated member of the firm — a Reviewer, who is read-only
--     by design in core/permissions.py's Partner > Manager > Executive >
--     Reviewer > Client ladder — can insert, amend or delete a statutory
--     deduction row or a TDS return. No audit_log entry is written either,
--     because log_event only runs on the API path.
--
--     Migrations 260 and 261 added exactly this rule to twenty-three tables.
--     They never reached the TDS four, and the test that exists to catch that
--     could not see the writes (see the scan fix in
--     tests/test_direct_write_tables_are_role_guarded.py).
--
-- WHICH TIER, AND WHY THIS ONE
--     Copied from the endpoints, not invented. Every write route in
--     routers/tds_workspace.py is guarded rbac("tds", "compute"):
--         POST /challans        :264
--         POST /returns         :357
--         PATCH /returns/status :424
--         POST /certificates    :536
--     and core/permissions.py:195 puts tds:compute at _AT_LEAST_EXECUTIVE.
--     So INSERT and UPDATE require Executive.
--
--     DELETE takes the higher tier. There is no tds:delete action to copy, and
--     migration 260's header settles that case: "removing a row is at least as
--     privileged as changing one, and the alternative (leaving DELETE
--     unguarded) is the bug this migration exists to close." tds:write is
--     _AT_LEAST_MANAGER (permissions.py:202), so DELETE requires Manager.
--     Deleting a filed quarter's deduction rows is not data entry.
--
--     The status ladder inside the API is unchanged and still stricter where it
--     needs to be: tds_workspace.py:443-448 requires Manager+ to approve or
--     file a return, on top of the Executive gate on the route. RLS cannot see
--     a status transition, so that check stays where it is.
--
-- RESTRICTIVE, AND PER COMMAND — both deliberate, both load-bearing
--     RESTRICTIVE because the existing firm-scoped policies are PERMISSIVE and
--     OR together: a permissive addition WIDENS access while reading in a diff
--     exactly like a tightening. A restrictive policy ANDs, which is the only
--     way to narrow what is already there.
--
--     PER COMMAND because a RESTRICTIVE ... FOR ALL policy applies its USING to
--     SELECT as well, and tds:read is _ALL_STAFF — a FOR ALL rule would stop a
--     Reviewer READING the register they are entitled to see. Same reasoning as
--     260 and 261, which is why this migration emits the same three policies.
--
-- tds_challans and tds_certificates have no browser writer today. They are
-- guarded anyway: it costs nothing, and the next screen that writes one should
-- find the rule already there rather than discover it is missing.
-- ============================================================================

DO $$
DECLARE
  -- (table, minimum role for INSERT/UPDATE, minimum role for DELETE)
  pol  text[][] := ARRAY[
    ['tds_deductions',   'Executive', 'Manager'],
    ['tds_returns',      'Executive', 'Manager'],
    ['tds_challans',     'Executive', 'Manager'],
    ['tds_certificates', 'Executive', 'Manager']
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

    -- Skip a table this database does not have rather than abort the whole
    -- migration — the same posture migration 260 takes, for the same reason.
    IF to_regclass('public.' || quote_ident(t)) IS NULL THEN
      RAISE NOTICE 'migration 345: skipping %, table not present', t;
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
