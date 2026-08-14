-- Migration 260: the database checks the caller's ROLE before allowing a write.
--
-- WHAT WAS WRONG
-- Row-level security on these tables enforced two things well — firm isolation
-- (firm_id = get_my_firm_id()) and client-assignment scope (can_access_client) —
-- and nothing at all about seniority. The API has always enforced the third:
-- rbac("accounting", "write") admits Manager and up, rbac("billing", "write")
-- only a Partner. But several screens talk to PostgREST directly rather than
-- through the API, and those writes never met that rule. An Executive or
-- Reviewer could edit a chart of accounts, a fee invoice or a firm's settings
-- straight from the browser, for any client assigned to them.
--
-- Hiding the button does not fix that. The button is not the boundary; anyone
-- holding a session token can issue the request without one. The boundary has
-- to be here, where every client — the app, curl, the PostgREST console —
-- passes through the same check.
--
-- WHY RESTRICTIVE
-- The existing per-table policies are PERMISSIVE and OR together, so adding
-- another permissive policy would WIDEN access, not narrow it. These are
-- RESTRICTIVE: they AND with whatever is already there. Firm isolation and
-- assignment scope keep applying exactly as before; this only adds a condition.
-- It is the same layering migration 073 used for `clients_internal_partner_only`.
--
-- WHY PER-COMMAND
-- A RESTRICTIVE ... FOR ALL policy applies its USING clause to SELECT too, so a
-- single policy would also gate reading — which is not the rule. INSERT, UPDATE
-- and DELETE are therefore declared separately and SELECT is left untouched:
-- who may LOOK at these tables is unchanged by this migration.
--
-- SCOPE — 9 TABLES, EACH MIRRORING AN EXISTING API RULE
-- Every requirement below was read off a live rbac() guard on an endpoint that
-- writes the same table, not chosen here. Tables the browser writes that have
-- NO API endpoint (compliance_calendar, it_notices, suppliers, tax_audits,
-- shared_reports, scheduled_reports, leave_balances, attendance, msme_payments,
-- tax_planning_records, client_documents, document_requests) are deliberately
-- NOT in this migration: there is no existing decision to mirror, and inventing
-- one would silently lock someone out of their job with no way to tell why.
-- tests/test_direct_write_tables_are_role_guarded.py enumerates them so the
-- remainder is tracked rather than forgotten.
--
-- BLAST RADIUS
-- The FastAPI backend is unaffected either way: with USE_USER_JWT off it holds
-- the service role, which bypasses RLS entirely; with it on it acts as the
-- caller, and these rules agree with the rbac() guard that already ran. What
-- changes is the direct-from-browser path, which is the point.

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. Role ranking, matching core/permissions.py
-- ─────────────────────────────────────────────────────────────────────────────
-- The Python tiers (_ALL_STAFF, _AT_LEAST_EXECUTIVE, _AT_LEAST_MANAGER,
-- _PARTNER_ONLY) are all prefixes of ROLE_HIERARCHY, so "at least X" expresses
-- every one of them without restating the matrix table by table.
--
-- Legacy vocabulary is normalised here for the same reason LEGACY_ROLE_MAP
-- exists in Python: rows written under the CHECK constraints in migrations
-- 001/021/022 can still carry owner/admin/article/staff/viewer, and a Partner
-- stored as 'owner' must not be locked out of their own firm by this change.
-- tests/test_sql_role_ranks_match_python.py holds the two in step.
CREATE OR REPLACE FUNCTION public.role_rank(role_name text)
RETURNS int
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE lower(coalesce(trim(role_name), ''))
    WHEN 'partner'   THEN 4
    WHEN 'owner'     THEN 4   -- legacy: firm owner
    WHEN 'manager'   THEN 3
    WHEN 'admin'     THEN 3   -- legacy: admin access level
    WHEN 'executive' THEN 2
    WHEN 'article'   THEN 2   -- legacy: delivery staff
    WHEN 'staff'     THEN 2   -- legacy: delivery staff
    WHEN 'reviewer'  THEN 1
    WHEN 'viewer'    THEN 1   -- legacy: read/approve-only
    WHEN 'client'    THEN 0
    ELSE -1                   -- unknown role: outranks nothing (fails closed)
  END;
$$;

-- True when the caller's role is at or above `minimum` in the hierarchy.
-- An unrecognised `minimum` yields false rather than true — a typo in a policy
-- must deny, not admit. SECURITY DEFINER because get_my_role() reads `users`.
CREATE OR REPLACE FUNCTION public.my_role_at_least(minimum text)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT public.role_rank(public.get_my_role()) >= 0
     AND public.role_rank(minimum) >= 0
     AND public.role_rank(public.get_my_role()) >= public.role_rank(minimum);
$$;

REVOKE ALL ON FUNCTION public.my_role_at_least(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.my_role_at_least(text) TO authenticated, anon, service_role;
REVOKE ALL ON FUNCTION public.role_rank(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.role_rank(text) TO authenticated, anon, service_role;

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. Per-table write requirements
-- ─────────────────────────────────────────────────────────────────────────────
-- Emitted by a loop rather than 27 hand-written statements: the mapping is the
-- content here, and spelling out three near-identical CREATE POLICY bodies per
-- table would bury it. The `pol` array is (table, min_role_for_insert_update,
-- min_role_for_delete).
--
-- Where the matrix defines no `delete` action for a resource, delete takes the
-- write tier — removing a row is at least as privileged as changing one, and
-- the alternative (leaving DELETE unguarded) is the bug this migration exists
-- to close.
DO $$
DECLARE
  pol  text[][] := ARRAY[
    -- accounting:write = Manager+  (routers/accounting.py create_account/update_account).
    -- No accounting:delete action exists, so delete inherits the write tier.
    ['chart_of_accounts',  'Manager',   'Manager'],
    -- client:write = Manager+, client:delete = Partner (routers/clients.py).
    ['clients',            'Manager',   'Partner'],
    -- customers is governed by the SAME resource: routers/customers.py guards
    -- create/update with client:write and delete_customer with client:delete.
    ['customers',          'Manager',   'Partner'],
    -- task:write = Executive+, task:delete = Manager+.
    ['tasks',              'Executive', 'Manager'],
    -- document:write = Executive+, document:delete = Partner.
    ['documents',          'Executive', 'Partner'],
    -- billing:* = Partner only — "exposes fee economics" (core/permissions.py).
    ['fee_invoices',       'Partner',   'Partner'],
    ['fee_engagements',    'Partner',   'Partner'],
    -- mca:write = Executive+ (routers/mca_workspace.py inserts mca_filings).
    -- No mca:delete action; delete inherits the write tier.
    ['mca_filings',        'Executive', 'Executive'],
    -- firm:write = Partner. Two direct writers agree: the firm settings page,
    -- and the year-lock toggle whose API twin is rbac("accounting","approve"),
    -- also Partner-only (routers/accounting.py set_year_lock).
    ['firms',              'Partner',   'Partner']
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
    -- migration: the set of tables differs across older branches, and one
    -- absent table must not block the other eight from being protected.
    IF to_regclass('public.' || quote_ident(t)) IS NULL THEN
      RAISE NOTICE 'migration 260: skipping %, table not present', t;
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

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. Invariant — every policy this migration claims to create actually exists
-- ─────────────────────────────────────────────────────────────────────────────
-- The DO block above swallows a missing table on purpose. This makes sure it
-- swallowed nothing else: for every table that IS present, all three policies
-- must be there and RESTRICTIVE. A permissive one would widen access while
-- looking like it narrowed it, which is the worst possible failure here.
DO $$
DECLARE
  expected text[] := ARRAY['chart_of_accounts','clients','customers','tasks','documents',
                           'fee_invoices','fee_engagements','mca_filings','firms'];
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
    RAISE EXCEPTION 'migration 260: role write policies incomplete on: %',
      array_to_string(missing, ', ');
  END IF;
END $$;
