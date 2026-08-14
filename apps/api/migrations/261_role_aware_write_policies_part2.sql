-- Migration 261: role-aware write policies for the remaining direct-write tables.
--
-- Migration 260 covered the nine tables where an API endpoint's rbac() guard on
-- the SAME table could be copied verbatim. These thirteen had no such endpoint —
-- the browser is their only writer — so 260 deliberately left them alone rather
-- than invent a rule. The rules are settled here, each from the evidence named
-- against it, and none from taste.
--
-- Two questions turned out to have answers in the code rather than needing one:
--
--   * attendance / leave_balances looked like they might be staff self-service,
--     which would have made payroll's Manager+ tier wrong. They are not: the
--     employee portal (app/portal/employee/page.tsx) only ever SELECTs them.
--     Every write comes from the staff payroll screen, and payroll.py guards
--     every one of its endpoints with payroll:read/write — Manager and up.
--
--   * client_timeline_events looked like it needed a tier of its own. It does,
--     but a permissive one: it is an append-only record of work that already
--     happened, written as a side effect of actions that each carry their own
--     guard. The least privileged of those (document:approve) admits Reviewer,
--     so requiring more here would break logging for work the person was
--     entitled to do. Hence the new `timeline` resource, _ALL_STAFF — and note
--     that UPDATE and DELETE are not granted to `authenticated` on that table at
--     all, so history still cannot be rewritten from a browser.
--
-- THREE JUDGEMENT CALLS, stated plainly so they can be overruled:
--
--   1. it_notices / tax_audits / tax_planning_records → income_tax. That
--      resource has read/compute/approve and no `write`, so `compute`
--      (Executive+) is used as the write tier: it is the do-the-work action for
--      income tax, and every income-tax endpoint already gates work on it.
--      Deletion takes `approve` (Manager+) — removing a notice is a heavier act
--      than recording one.
--   2. suppliers / msme_payments → accounting:write (Manager+). Both are
--      firm-level records under the Accounting workspace. `suppliers` is
--      distinct from `vendors`, whose API twin is guarded by client:write —
--      also Manager+, so the two readings agree and the choice does not matter.
--   3. compliance_calendar → compliance:write (Executive+). Its only writers are
--      the GST screen's filing-status updates; gst:compute is also Executive+,
--      so again both readings land on the same tier.
--
-- Everything else is a direct read of the matrix. Mechanics — RESTRICTIVE so the
-- policies AND with the existing firm-isolation and assignment-scope rules
-- rather than widening them, and per-command so SELECT is untouched — are
-- unchanged from 260, as are role_rank()/my_role_at_least(), which this
-- migration reuses rather than redefines.

DO $$
DECLARE
  pol  text[][] := ARRAY[
    -- payroll:write = Manager+ (routers/payroll.py, every endpoint).
    ['attendance',             'Manager',   'Manager'],
    ['leave_balances',         'Manager',   'Manager'],
    -- compliance:write = Executive+, compliance:delete = Partner.
    ['compliance_calendar',    'Executive', 'Partner'],
    -- income_tax:compute = Executive+, income_tax:approve = Manager+.
    ['it_notices',             'Executive', 'Manager'],
    ['tax_audits',             'Executive', 'Manager'],
    ['tax_planning_records',   'Executive', 'Manager'],
    -- report:write = Manager+ (no report:delete action; delete takes the write
    -- tier, as in 260 — removing a row is at least as privileged as changing it).
    ['shared_reports',         'Manager',   'Manager'],
    ['scheduled_reports',      'Manager',   'Manager'],
    -- document:write = Executive+, document:delete = Partner.
    ['client_documents',       'Executive', 'Partner'],
    -- portal:write = Executive+ (routers/portal.py owns document_requests; its
    -- list endpoint is rbac("portal","read")). No portal:delete action.
    ['document_requests',      'Executive', 'Executive'],
    -- accounting:write = Manager+.
    ['suppliers',              'Manager',   'Manager'],
    ['msme_payments',          'Manager',   'Manager'],
    -- timeline:write = _ALL_STAFF, i.e. Reviewer and above; Client excluded.
    -- Delete is Partner despite no DELETE grant existing today: if a grant is
    -- ever added, the policy should already be there rather than have to be
    -- remembered.
    ['client_timeline_events', 'Reviewer',  'Partner']
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
      RAISE NOTICE 'migration 261: skipping %, table not present', t;
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

-- Same invariant as 260: the loop skips an absent table on purpose, so prove it
-- skipped nothing else. A PERMISSIVE policy here would widen access while
-- reading, in a diff, exactly like a tightening.
DO $$
DECLARE
  expected text[] := ARRAY['attendance','leave_balances','compliance_calendar','it_notices',
                           'tax_audits','tax_planning_records','shared_reports',
                           'scheduled_reports','client_documents','document_requests',
                           'suppliers','msme_payments','client_timeline_events'];
  t       text;
  missing text[] := '{}';
  n       int;
BEGIN
  FOREACH t IN ARRAY expected LOOP
    IF to_regclass('public.' || quote_ident(t)) IS NULL THEN
      CONTINUE;
    END IF;
    SELECT count(*) INTO n
      FROM pg_policies
     WHERE schemaname = 'public'
       AND tablename  = t
       AND permissive = 'RESTRICTIVE'
       AND policyname IN (t || '_role_insert', t || '_role_update', t || '_role_delete');
    IF n <> 3 THEN
      missing := missing || (t || ' (' || n || '/3)');
    END IF;
  END LOOP;

  IF array_length(missing, 1) IS NOT NULL THEN
    RAISE EXCEPTION 'migration 261: role write policies incomplete on: %',
      array_to_string(missing, ', ');
  END IF;
END $$;
