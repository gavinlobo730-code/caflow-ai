-- 415 — the per-person permission grid reaches the database
--
-- ── WHAT WAS WRONG ───────────────────────────────────────────────────────────
--
-- Migration 403 made access PER PERSON: `user_permissions` holds one row per
-- (person, resource, action), and `core.permissions.resolve_permission` is the
-- rule — a row WINS however junior or senior the role, and no row means the
-- role decides. `rbac()` resolves it at one seam, which is why all 1037 of its
-- call sites got per-person access without being touched.
--
-- THE DATABASE NEVER LEARNED. Migration 260 put RESTRICTIVE write policies on
-- nine tables, every one of them keyed on `my_role_at_least(...)`, which asks
-- `get_my_role()` and nothing else. And `USE_USER_JWT` is TRUE in production —
-- render.yaml records it in its own comment, `sync: false`, so no test can see
-- the value — which means the backend queries as `authenticated` and RLS is
-- enforced on the API path too, not only on the ~83 tables the browser reads
-- over PostgREST.
--
-- So a firm that used the Team screen to grant one Manager `billing:write`
-- got a person who passes `rbac()` and is then refused by Postgres. The grid
-- is vetoed by the control it was built to replace, and the refusal arrives as
-- a PostgREST error the screen reports as "failed to save".
--
-- ── WHAT THIS DOES ───────────────────────────────────────────────────────────
--
-- `public.my_permission(resource, action, minimum_role)` is the SQL twin of
-- `resolve_permission`, and migration 260's nine tables ask it instead of
-- asking the role directly. THE MINIMUM ROLE IS UNCHANGED for every table, so
-- with an empty `user_permissions` this reproduces today's behaviour exactly —
-- 403 wrote no backfill, and the Team grid is the only writer.
--
-- ── THE THREE THINGS THIS DELIBERATELY DOES NOT DO ───────────────────────────
--
-- 1. IT DOES NOT HOLD THE VOCABULARY. `core/permissions.PERMISSIONS` is the
--    only list of valid (resource, action) pairs, and 403's own comment says
--    why a copy in SQL would be wrong: "a hand-copied list in SQL would be a
--    second authority". So this function does not validate the pair, and it
--    does not need to — the pair is a LITERAL in the policy, written by
--    whoever wrote the policy, not a value read out of a row. What keeps the
--    two in step is
--    `tests/test_the_per_person_grid_reaches_the_database.py`, which reads the
--    pairs back out of THIS FILE and asserts each is in PERMISSIONS.
--
-- 2. IT DOES NOT RESTATE THE HIERARCHY. The no-row branch CALLS
--    `my_role_at_least`, so there is one role ladder and `role_rank`'s legacy
--    aliases (owner/admin/article/staff/viewer) keep working here for free.
--
-- 3. IT DOES NOT CHANGE ANY TABLE'S MINIMUM ROLE. Whether a fee engagement is
--    governed by `billing` or by `engagement` was the other half of question
--    G2 and is answered at the API, in the commit before this one, where the
--    disagreement actually was.
--
-- ── THE PARTNER BACKSTOP ─────────────────────────────────────────────────────
--
-- `resolve_permission` ignores a `granted = false` row for four pairs when the
-- caller is a Partner, because without it the grid is unrepairable: the only
-- person who could restore access is the one whose access was removed, and
-- `team:write` is the only thing that can write the table. The same four are
-- named below. That IS a second copy of a list, which is why the test file
-- above pins it to `core.permissions.UNREVOKABLE_FOR_PARTNER` FROM THE PYTHON
-- SIDE — the Schedule III caption lesson: a guard written in SQL would assert
-- the list against a copy of itself.
--
-- ── WHY plpgsql AND NOT sql ──────────────────────────────────────────────────
--
-- `my_role_at_least` is a one-line `LANGUAGE sql` function and this one could
-- not be: the three states (row says yes, row says no, no row) need the lookup
-- to happen ONCE and then be branched on. Written as SQL it would either
-- evaluate the subquery twice or fold the three states into two, and folding
-- them is the exact mistake 403's own column comment warns about.

CREATE OR REPLACE FUNCTION public.my_permission(
  resource      text,
  action        text,
  minimum_role  text
)
RETURNS boolean
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $$
DECLARE
  v_granted boolean;
BEGIN
  -- The person's own answer, if they have one. `granted` is NOT NULL and the
  -- ROW is what is optional, so "no opinion" has exactly one spelling and a
  -- NULL here means only that no row was found.
  SELECT up.granted
    INTO v_granted
    FROM public.user_permissions up
    JOIN public.users u ON u.id = up.user_id
   WHERE u.auth_user_id = auth.uid()
     AND up.resource = my_permission.resource
     AND up.action   = my_permission.action
   LIMIT 1;

  IF v_granted IS NULL THEN
    -- No row: the role decides, at the minimum this policy names.
    RETURN public.my_role_at_least(minimum_role);
  END IF;

  IF v_granted IS FALSE
     AND public.role_rank(public.get_my_role()) >= public.role_rank('Partner')
     AND (my_permission.resource, my_permission.action) IN
         (('team','read'), ('team','write'), ('firm','read'), ('firm','admin'))
  THEN
    -- A Partner keeps the four pairs that reach the access screen itself,
    -- whatever the grid says. See the header.
    RETURN true;
  END IF;

  RETURN v_granted;
END;
$$;

COMMENT ON FUNCTION public.my_permission(text, text, text) IS
  'The SQL twin of core.permissions.resolve_permission: a user_permissions row '
  'wins, and with no row the role decides at the given minimum. Holds no '
  'vocabulary — the pair is a literal in the policy that calls it, pinned to '
  'PERMISSIONS by tests/test_the_per_person_grid_reaches_the_database.py. '
  'Migration 415.';

REVOKE ALL ON FUNCTION public.my_permission(text, text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.my_permission(text, text, text)
  TO authenticated, anon, service_role;

-- ─────────────────────────────────────────────────────────────────────────────
-- The nine tables of migration 260, re-pointed at the grid
-- ─────────────────────────────────────────────────────────────────────────────
-- Derived from 260, which is still the last definer of these policies — found
-- by NUMBER rather than from memory, because `CREATE POLICY` after a `DROP`
-- replaces the whole thing, so a rewrite either carries every earlier change
-- forward or silently reverts it.
--
-- The array gains a RESOURCE column. 260 named each table's governing resource
-- in a COMMENT and then had no way to ask it; that is the whole gap this
-- closes. The role minimums are copied across unchanged.
DO $$
DECLARE
  pol text[][] := ARRAY[
    -- table,              resource,      insert/update role, delete role
    ['chart_of_accounts',  'accounting',  'Manager',   'Manager'],
    ['clients',            'client',      'Manager',   'Partner'],
    ['customers',          'client',      'Manager',   'Partner'],
    ['tasks',              'task',        'Executive', 'Manager'],
    ['documents',          'document',    'Executive', 'Partner'],
    ['fee_invoices',       'billing',     'Partner',   'Partner'],
    ['fee_engagements',    'billing',     'Partner',   'Partner'],
    ['mca_filings',        'mca',         'Executive', 'Executive'],
    ['firms',              'firm',        'Partner',   'Partner']
  ];
  t         text;
  res       text;
  min_write text;
  min_del   text;
  del_act   text;
  i         int;
BEGIN
  FOR i IN 1 .. array_length(pol, 1) LOOP
    t         := pol[i][1];
    res       := pol[i][2];
    min_write := pol[i][3];
    min_del   := pol[i][4];

    -- 260's reason, unchanged: skip a table this database does not have rather
    -- than abort and leave the other eight unprotected.
    IF to_regclass('public.' || quote_ident(t)) IS NULL THEN
      RAISE NOTICE 'migration 415: skipping %, table not present', t;
      CONTINUE;
    END IF;

    -- DELETE asks the `delete` action where the matrix defines one and `write`
    -- where it does not. That is 260's own rule about the ROLE ("where the
    -- matrix defines no delete action, delete takes the write tier") restated
    -- about the PAIR, and getting it wrong locks a table rather than opening
    -- it: `resolve_permission` treats a pair PERMISSIONS does not define as
    -- INERT and falls through to `can`, which fails closed, so a policy naming
    -- a non-existent action refuses EVERYBODY including a Partner.
    --
    -- Only client, task and document have one. `billing` does NOT — the first
    -- draft of this migration listed it, which would have made every fee
    -- invoice and fee engagement permanently undeletable, and
    -- `tests/test_the_per_person_grid_reaches_the_database.py` caught it. The
    -- set is asserted against PERMISSIONS there rather than trusted here.
    del_act := CASE WHEN res IN ('client','task','document')
                    THEN 'delete' ELSE 'write' END;

    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_insert', t);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR INSERT '
      'WITH CHECK (public.my_permission(%L, %L, %L))',
      t || '_role_insert', t, res, 'write', min_write);

    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_update', t);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR UPDATE '
      'USING (public.my_permission(%L, %L, %L)) '
      'WITH CHECK (public.my_permission(%L, %L, %L))',
      t || '_role_update', t, res, 'write', min_write, res, 'write', min_write);

    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_delete', t);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR DELETE '
      'USING (public.my_permission(%L, %L, %L))',
      t || '_role_delete', t, res, del_act, min_del);
  END LOOP;
END $$;

-- ─────────────────────────────────────────────────────────────────────────────
-- Invariant — 260's own check, restated against the new predicate
-- ─────────────────────────────────────────────────────────────────────────────
-- The DO block above swallows a missing table on purpose. This makes sure it
-- swallowed nothing else. A PERMISSIVE policy here would widen access while
-- looking like it narrowed it, which is the worst possible failure; and a
-- policy still asking `my_role_at_least` would be one this migration claims to
-- have converted and did not.
DO $$
DECLARE
  expected text[] := ARRAY['chart_of_accounts','clients','customers','tasks','documents',
                           'fee_invoices','fee_engagements','mca_filings','firms'];
  t       text;
  bad     text[] := '{}';
  n       int;
BEGIN
  FOREACH t IN ARRAY expected LOOP
    IF to_regclass('public.' || quote_ident(t)) IS NULL THEN
      CONTINUE;
    END IF;
    SELECT count(*) INTO n
      FROM pg_policies
     WHERE schemaname  = 'public'
       AND tablename   = t
       AND permissive  = 'RESTRICTIVE'
       AND policyname IN (t || '_role_insert', t || '_role_update', t || '_role_delete')
       AND coalesce(qual, '') || coalesce(with_check, '') LIKE '%my_permission%';
    IF n <> 3 THEN
      bad := bad || (t || ' has ' || n || ' of 3');
    END IF;
  END LOOP;
  IF array_length(bad, 1) IS NOT NULL THEN
    RAISE EXCEPTION 'migration 415: policies not converted: %', array_to_string(bad, ', ');
  END IF;
END $$;
